#!/usr/bin/env python3
"""shrooms_build.py - generates the static data for https://shrooms.strong.beer from the oregon-mushroom-scout skill.

Modes:
  fill [--minutes N]     fetch missing ERA5-Land archive files (lite = scoring inputs, full = 23 weather measures) until the free
                         API's daily quota says stop, then rebuild everything from the caches
  rebuild                rebuild every output from the caches, no network
  nightly                extend the current year's archive tail, compute LIVE scores for zones + sample points, history-based
                         outlook, store snapshots and weather in SQLite, write all site data (+ optional Gemini brief)
  auto                   cron tick (hourly): runs `nightly` once a day after 06:00 Pacific, otherwise continues `fill`
  zones                  rewrite zones.json only
All output is static JSON in /opt/shrooms/site/data. No keys, no home coordinates, nothing private is ever written there.

History method (faithful to the live pipeline): for every past day D and zone, rebuild the same derived features the live
weather.py produces (7-day soil temp/moisture means, 7/14/30-day rain, last rain event, frost nights, air temp, SNOTEL
melt-out date for high-elevation spring species, rain-based season opener for fall species) from ERA5-Land archive data and
run the skill's own score.score_species with "today" faked to D. Caveat: the archive is a reanalysis (soil 0-7 cm), the live
pipeline uses forecast-model soil temperature (6 cm); they track each other but are not identical.
"""
import copy
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import om_key                                           # Open-Meteo commercial key support (customer host + apikey, free-host fallback)
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SKILL = os.environ.get("SHROOMS_SKILL", "/opt/mushroom-scout")
SCRIPTS = SKILL + "/scripts"
ROOT = os.environ.get("SHROOMS_ROOT", "/opt/shrooms")
SITE_DATA = os.environ.get("SHROOMS_SITE_DATA", ROOT + "/site/data")
CACHE = ROOT + "/cache"
DBFILE = ROOT + "/data/live_history.sqlite"
sys.path.insert(0, SCRIPTS)
import score as sc      # noqa: E402  (the skill's scorer, unchanged)
import snotel           # noqa: E402  (the skill's SNOTEL helper, unchanged)

TZ = ZoneInfo("America/Los_Angeles")
UA = {"User-Agent": "shrooms-tracker (static site generator)"}
FINE_PRINT = ("Never eat any wild mushroom you have not positively identified yourself - scores predict fruiting "
              "conditions, not what is actually in your basket. When in doubt, throw it out, or run finds past the "
              "Cascade Mycological Society (Eugene) or Central Oregon Mushroom Club (Bend). Check permit rules for "
              "the land unit before picking; rules change.")


PDX = (45.5152, -122.6784)      # downtown Portland, used only for the "distance from Portland" filter


def haversine_km(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2 +
         math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def load_extras():
    """Extra zones/permits that belong to the website only (the skill's own files are never modified)."""
    zx = json.load(open(ROOT + "/zones_extra.json"))
    try:
        px = json.load(open(ROOT + "/permits_extra.json")).get("entries", [])
    except Exception:
        px = []
    return zx, px


_REG_CACHE = {}


def reg_for(reg, zone):
    """Workaround for a bug in the skill's species_registry.json (left unmodified): king_fall.elev_bands_ft is keyed
    {'coastal','interior'} but score.check_gates only understands 'all' or month numbers, so fall kings are ALWAYS gated
    out ('no elevation band for month N'). Here the intended band is applied per zone: coastal 0-1500 ft, interior 3500-6000 ft."""
    key = bool(zone.get("coastal"))
    if key not in _REG_CACHE:
        r = copy.deepcopy(reg)
        kf = r["species"].get("king_fall")
        if kf and "all" not in kf.get("elev_bands_ft", {}) and "coastal" in kf.get("elev_bands_ft", {}):
            bands = kf["elev_bands_ft"]
            kf["elev_bands_ft"] = {"all": list(bands["coastal"] if key else bands["interior"])}
        _REG_CACHE[key] = r
    return _REG_CACHE[key]


def log(msg):
    print("%s %s" % (datetime.now(TZ).strftime("%F %T"), msg), flush=True)


def kuma_push(status, msg):
    """Heartbeat to the Kuma push monitor named in /etc/shrooms/build.json (silently skipped if absent)."""
    try:
        k = json.load(open("/etc/shrooms/build.json"))["kuma"]
        q = urllib.parse.urlencode({"status": status, "msg": msg[:200], "ping": ""})
        urllib.request.urlopen("%s/%s?%s" % (k["base"].rstrip("/"), k["token"], q), timeout=15).read()
    except Exception as exc:
        log("note: kuma push skipped/failed: %s" % exc)


def atomic_write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, path)


# ---------------------------------------------------------------- permits (from the skill's own file only)
def load_permits():
    txt = open(SKILL + "/references/permits.md").read()
    perms = {}
    for m in re.finditer(r"### (.+?)\n\*\*Last verified: (\d{4}-\d{2}-\d{2})\*\*\n\*\*Rule:\*\* (.*?)(?=\nSource:|\n###|\n---|\Z)", txt, re.S):
        perms[m.group(1).strip()] = (m.group(2), " ".join(m.group(3).split()))
    return perms


def permit_for(zone, perms, extras=()):
    out, newest_old = [], False
    today = datetime.now(TZ).date()
    for name, (ver, rule) in perms.items():
        short = name.replace("National Forest", "NF")
        if short in zone.get("land", ""):
            if len(rule) > 300:
                rule = "Rules differ here and could not be confirmed online - call the ranger district before picking."
            if (today - datetime.strptime(ver, "%Y-%m-%d").date()).days > 365:
                newest_old = True
            out.append("%s: %s" % (short, rule))
    for e in extras:
        if any(m in zone.get("land", "") for m in e["match"]):
            out.append("%s: %s" % (e["name"], e["rule"]))
            if e.get("verify") or (today - datetime.strptime(e["verified"], "%Y-%m-%d").date()).days > 365:
                newest_old = True
    if zone["id"] == "diamond_lemolo":
        out.append("Crater Lake NP: NO mushroom collecting - stay outside the park boundary.")
    return {"text": " | ".join(out), "verify_before_you_go": newest_old}


def species_in_window(reg, key, zone, month):
    sp = sc.get_species_config(reg, key)
    if "months" in sp:
        return month in sp["months"]
    return month in (sp.get("months_coastal", []) if zone.get("coastal") else sp.get("months_interior", []))


def zone_species(reg, zone):
    return [k for k in zone.get("species", []) if k != "morel_burn"]


def has_data(per_year):
    return any(v is not None for arr in per_year.values() for v in arr)


def prune_series(series):
    return {k: v for k, v in series.items() if has_data(v)}


def build_zones(reg, zones, perms, extras_cfg, perm_extras, series):
    """zones.json. Species are listed only when the model can ever score them in that zone (non-empty hindcast series)."""
    out = []
    ids_with = {}
    for key in series:
        zid, sp = key.split("|")
        ids_with.setdefault(zid, set()).add(sp)
    by_skill = extras_cfg.get("regions_by_skill_zone", {})
    extra_ids = {z["id"]: z for z in extras_cfg["zones"]}
    for z in zones:
        keys = zone_species(reg, z)
        if series:
            keys = [k for k in keys if k in ids_with.get(z["id"], set())]
            if not keys:                                        # new zone whose history is still being downloaded: not listed yet
                continue
        x = extra_ids.get(z["id"], {})
        out.append({
            "id": z["id"], "name": z["name"], "lat": z["lat"], "lon": z["lon"], "elev_ft": z["elev_ft"],
            "side": z.get("side"), "coastal": bool(z.get("coastal")), "land": z.get("land", ""),
            "habitat": z.get("habitat", ""),
            "species": [{"key": k, "display": reg["species"][k]["display"]} for k in keys],
            "permit": permit_for(z, perms, perm_extras),
            "pdx_km": round(haversine_km(PDX[0], PDX[1], z["lat"], z["lon"])),
            "pdx_drive_h": x.get("pdx_drive_h"),
            "regions": x.get("regions") or by_skill.get(z["id"], []),
            "sightings": x.get("sightings"),
        })
    return out


# ---------------------------------------------------------------- archive fetch (lite = scoring inputs, full = everything we keep)
LITE_DAILY = "precipitation_sum,temperature_2m_min,temperature_2m_max"
LITE_HOURLY = "soil_temperature_0_to_7cm,soil_moisture_0_to_7cm"      # snow_depth is not used by the scorer
FULL_DAILY = ("precipitation_sum,rain_sum,snowfall_sum,temperature_2m_min,temperature_2m_max,et0_fao_evapotranspiration,"
              "sunshine_duration,shortwave_radiation_sum")
FULL_HOURLY = ("soil_temperature_0_to_7cm,soil_temperature_7_to_28cm,soil_temperature_28_to_100cm,soil_moisture_0_to_7cm,"
               "soil_moisture_7_to_28cm,soil_moisture_28_to_100cm,snow_depth,temperature_2m,relative_humidity_2m,dew_point_2m,"
               "vapour_pressure_deficit,wind_speed_10m,surface_pressure,cloud_cover,shortwave_radiation")
PACE = 1.0          # seconds between archive calls (the free API also has a daily weighted quota; see DailyLimit)


class DailyLimit(Exception):
    pass


def paths_for(zone, year):
    return "%s/arch2_%s_%d.json" % (CACHE, zone["id"], year), "%s/arch_%s_%d.json" % (CACHE, zone["id"], year)


def source_path(zone, year):
    for p in paths_for(zone, year):          # full file first, lite file otherwise
        if os.path.exists(p):
            return p
    return None


def archive_url(zone, start, end, full):
    return ("https://archive-api.open-meteo.com/v1/archive?latitude=%s&longitude=%s&start_date=%s&end_date=%s&daily=%s&hourly=%s"
            "&temperature_unit=fahrenheit&precipitation_unit=inch&wind_speed_unit=mph&timezone=America%%2FLos_Angeles"
            % (zone["lat"], zone["lon"], start, end, FULL_DAILY if full else LITE_DAILY, FULL_HOURLY if full else LITE_HOURLY))


def http_json(url, what):
    last = None
    for attempt in range(7):
        try:
            with om_key.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                data = json.loads(r.read().decode())
            if "daily" in data:
                time.sleep(PACE)
                return data
            last = data
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode()[:200]
            except Exception:
                pass
            last = "HTTP %s %s" % (exc.code, body)
            if exc.code == 429 and "Daily" in body:
                raise DailyLimit(body)
            if exc.code == 429 and "Hourly" in body:
                time.sleep(300)
        except Exception as exc:
            last = str(exc)
        time.sleep(min(60, 10 * (attempt + 1)))
    log("warn: archive fetch failed for %s: %s" % (what, str(last)[:160]))
    return None


def splice(old, new, start_iso):
    for sec in ("daily", "hourly"):
        times = old[sec]["time"]
        idx = next((i for i, t in enumerate(times) if t >= start_iso), len(times))
        n_new = len(new[sec]["time"])
        for k in old[sec]:
            old[sec][k] = old[sec][k][:idx] + (new[sec].get(k) or [None] * n_new)
    return old


def save_json(path, obj):
    tmp = path + ".tmp"
    json.dump(obj, open(tmp, "w"))
    os.replace(tmp, path)


def fetch_year(zone, year, net=False, full=False):
    """ERA5-Land archive for [Dec 1 of year-1 .. min(Dec 31, today-6d)]. Cache-only unless net=True. The current year's file is
    extended in place (only the missing tail is requested), so the nightly refresh is tiny."""
    os.makedirs(CACHE, exist_ok=True)
    now = datetime.now(TZ)
    cur = now.year
    p2, p1 = paths_for(zone, year)
    end_d = min(date(year, 12, 31), now.date() - timedelta(days=6))
    start0 = "%d-12-01" % (year - 1)
    start_lite = "%d-01-25" % year if year < cur else start0       # past years: scoring only needs a 30-day lead-in before March
    what = "%s %d%s" % (zone["id"], year, " full" if full else "")
    if end_d <= date(year - 1, 12, 31):
        return None
    if year < cur:
        if full:
            if os.path.exists(p2):
                return json.load(open(p2))
        else:
            sp = source_path(zone, year)
            if sp:
                return json.load(open(sp))
        if not net:
            return None
        data = http_json(archive_url(zone, start0 if full else start_lite, end_d.isoformat(), full), what)
        if data:
            save_json(p2 if full else p1, data)
        return data
    path = p2 if os.path.exists(p2) else (p1 if os.path.exists(p1) else None)
    if full and not os.path.exists(p2):
        if not net:
            return json.load(open(path)) if path else None
        data = http_json(archive_url(zone, start0, end_d.isoformat(), True), what)
        if data:
            save_json(p2, data)
        return data
    if path is None:
        if not net:
            return None
        data = http_json(archive_url(zone, start0, end_d.isoformat(), False), what)
        if data:
            save_json(p1, data)
        return data
    data = json.load(open(path))
    if net and data["daily"]["time"] and data["daily"]["time"][-1] < end_d.isoformat():
        s = (date.fromisoformat(data["daily"]["time"][-1]) - timedelta(days=3)).isoformat()
        new = http_json(archive_url(zone, s, end_d.isoformat(), path == p2), what + " tail")
        if new:
            data = splice(data, new, s)
            save_json(path, data)
    return data


def daily_means(hourly_times, values):
    acc = {}
    for t, v in zip(hourly_times, values):
        if v is not None:
            d = t.split("T")[0]
            s, n = acc.get(d, (0.0, 0))
            acc[d] = (s + v, n + 1)
    return {d: s / n for d, (s, n) in acc.items()}


def melt_out_for(zone, year, cache):
    key = (zone["id"], year)
    if key in cache:
        return cache[key]
    val = None
    try:
        st = snotel.find_nearest_station(zone["lat"], zone["lon"])
        if "error" not in st:
            info = snotel.find_melt_out_date(st, year)
            val = info.get("melt_out_date")
    except Exception as exc:
        log("warn: snotel %s %d: %s" % (zone["id"], year, exc))
    cache[key] = val
    return val


class FakeDT(datetime):
    """score.py calls datetime.utcnow() to mean 'today'; for history we pin it to the simulated day."""
    _now = datetime(2000, 1, 1)

    @classmethod
    def utcnow(cls):
        return cls._now


def features_at(i, dates, precip, tmin, tmax, soil_t, soil_m):
    def win(arr, n):
        return arr[max(0, i - n + 1): i + 1]

    def mean(vals):
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None
    f = {
        "soil_t_7d_mean": mean(win(soil_t, 7)),
        "soil_moisture_7d_mean": mean(win(soil_m, 7)),
        "precip_7d": sum((p or 0) for p in win(precip, 7)),
        "precip_14d": sum((p or 0) for p in win(precip, 14)),
        "precip_30d": sum((p or 0) for p in win(precip, 30)),
        "air_temp_7d_mean_max": mean(win(tmax, 7)),
        "frost_nights_last3": sum(1 for t in win(tmin, 3) if (t if t is not None else 100) <= 28),
        "frost_nights_last5": sum(1 for t in win(tmin, 5) if (t if t is not None else 100) <= 28),
        "last_rain_event": None,
    }
    for threshold in (0.1, 0.5, 1.0):          # same detection logic as the skill's weather.py
        last_rain, rolling = None, 0
        for j in range(i, -1, -1):
            rolling += precip[j] or 0
            if rolling >= threshold:
                last_rain = dates[j]
                break
            if j < i:
                rolling = 0
        if last_rain:
            f["last_rain_event"] = last_rain
            break
    return f


SCORE_VERSION = 3
NET_BLOCKED = [False]


def backfill_zone(reg, zone, years, snotel_cache, con=None, net_cur=False):
    """Returns {species: {year: [366 scores or None]}} for one zone/point. Per-year scored arrays are cached next to the weather
    cache and only recomputed when the weather file (or the zone definition) changes."""
    species = zone_species(reg, zone)
    out = {k: {} for k in species}
    cur = datetime.now(TZ).year
    for year in years:
        try:
            data = fetch_year(zone, year, net=(net_cur and year == cur and not NET_BLOCKED[0]))
        except DailyLimit:
            NET_BLOCKED[0] = True                        # archive quota used up: score from what is cached, retry tomorrow
            log("note: archive daily quota reached; using cached weather for the rest of this run")
            data = fetch_year(zone, year, net=False)
        if not data:
            continue
        sp_path = source_path(zone, year)
        st = os.stat(sp_path)
        sig = "%d:%d:%d:%s:%s:%s:%s" % (SCORE_VERSION, st.st_mtime_ns, st.st_size, zone["elev_ft"], zone.get("coastal"), zone.get("side"), ",".join(species))
        scp = "%s/sc_%s_%d.json" % (CACHE, zone["id"], year)
        try:
            c = json.load(open(scp))
            if c.get("sig") == sig:
                for k in species:
                    out[k][str(year)] = c["arr"][k]
                continue
        except Exception:
            pass
        if con is not None:
            try:
                store_weather(con, zone["id"], "era5", archive_days(data))
            except Exception as exc:
                log("warn: weather rows %s %d: %s" % (zone["id"], year, exc))
        dates = data["daily"]["time"]
        precip, tmin, tmax = data["daily"]["precipitation_sum"], data["daily"]["temperature_2m_min"], data["daily"]["temperature_2m_max"]
        ht = data["hourly"]["time"]
        soil_t_d = daily_means(ht, data["hourly"]["soil_temperature_0_to_7cm"])
        soil_m_d = daily_means(ht, data["hourly"]["soil_moisture_0_to_7cm"])
        soil_t = [soil_t_d.get(d) for d in dates]
        soil_m = [soil_m_d.get(d) for d in dates]
        aug1 = dates.index("%d-08-01" % year) if "%d-08-01" % year in dates else None
        need_melt = zone["elev_ft"] >= 3500 and any(k in ("morel_natural", "king_spring") for k in species)
        melt = melt_out_for(zone, year, snotel_cache) if need_melt else None
        arrays = {k: [None] * 366 for k in species}
        jan1 = date(year, 1, 1)
        for i, d in enumerate(dates):
            dd = date.fromisoformat(d)
            if dd.year != year:
                continue
            doy = (dd - jan1).days
            in_win = [k for k in species if species_in_window(reg, k, zone, dd.month)]
            if not in_win:
                continue
            w = features_at(i, dates, precip, tmin, tmax, soil_t, soil_m)
            if melt and 3 <= dd.month <= 7:
                w["melt_out_date"] = melt
            if dd.month >= 8 and aug1 is not None and i >= aug1:
                w["archive_data"] = {"daily": {"precipitation_sum": precip[aug1:i + 1], "time": dates[aug1:i + 1]}}
            w["data_timestamp"] = d
            FakeDT._now = datetime(dd.year, dd.month, dd.day, 12)
            sc.datetime = FakeDT
            for k in in_win:
                r = sc.score_species(reg_for(reg, zone), k, zone, dd.month, w)
                arrays[k][doy] = None if r["label"] == "gated out" else r["score"]
        sc.datetime = datetime
        for k in species:
            out[k][str(year)] = arrays[k]
        save_json(scp, {"sig": sig, "arr": arrays})
    sc.datetime = datetime
    return out


def run_backfill(reg, points, years, con=None, net_cur=False):
    """Scores every point (zones + unlisted grid) for the given years. Cheap when the per-year caches are warm."""
    series, snotel_cache = {}, {}
    for z in points:
        t0 = time.time()
        res = backfill_zone(reg, z, years, snotel_cache, con, net_cur)
        if con is not None:
            con.commit()
        for k, per_year in res.items():
            if per_year and has_data(per_year):
                series["%s|%s" % (z["id"], k)] = per_year
        if time.time() - t0 > 20:
            log("scored %-24s in %ds" % (z["id"], time.time() - t0))
    return series


def build_queue(points, years):
    """Network work still to do, most useful first: lite (scoring) files for every point newest year first, then the full
    23-measure files for the listed zones. Grid points never need the full set (their weather is stored nightly)."""
    lite, full = [], []
    # a point with no files at all (a newly added zone) is fetched first, every year, so it becomes usable quickly
    fresh = [p for p in points if sum(1 for y in years if source_path(p, y) is not None) <= len(years) // 2]      # (under half the years on file: a new or just-started zone)
    rest = [p for p in points if p not in fresh]
    for grp in (fresh, sorted(rest, key=lambda p: str(p["id"]).startswith("g_"))):      # listed zones before the unlisted heat-map grid points
        for y in sorted(years, reverse=True):
            for p in grp:
                if source_path(p, y) is None:
                    lite.append((p, y, False))
    for grp in (fresh, rest):
        for y in sorted(years, reverse=True):
            for p in grp:
                if p.get("lite"):
                    continue
                if not os.path.exists(paths_for(p, y)[0]):
                    full.append((p, y, True))
    return lite, full


def run_fill(points, years, con, minutes, lite_only=False):
    """Fetches queued archive files until the free API's daily quota says stop (then waits for the next UTC day) or time is up."""
    lim = ROOT + "/data/limit_until"
    try:
        until = datetime.fromisoformat(open(lim).read().strip())
        if datetime.utcnow() < until:
            log("fill: waiting for the archive quota to reset at %s UTC" % until.strftime("%F %H:%M"))
            return 0
    except Exception:
        pass
    lite, full = build_queue(points, years)
    full_first = os.path.exists(ROOT + "/data/full_first")      # lets two machines split the work (this one: big files first)
    tasks = lite if lite_only else (full + lite if full_first else lite + full)
    deadline = time.time() + minutes * 60
    done = 0
    spent = 0                                                   # estimated free-API call cost this run; the hourly cap is 5,000 and weather.py needs headroom
    ledger = ROOT + "/data/fill_spend.json"                     # the daily cap is 10,000: the backfill may use at most 4,500 so the nightly build and live fetches always have room
    day = datetime.utcnow().strftime("%F")
    try:
        led = json.load(open(ledger))
    except Exception:
        led = {}
    if led.get("day") != day:
        led = {"day": day, "spent": 0}
    try:
        for p, y, is_full in tasks:
            if time.time() > deadline or spent > 3500 or led["spent"] + spent > 4500:
                break
            spent += 42 if is_full else 26
            data = fetch_year(p, y, net=True, full=is_full)
            if data and is_full:
                try:
                    store_weather(con, p["id"], "era5", archive_days(data))
                    con.commit()
                except Exception as exc:
                    log("warn: weather rows %s %d: %s" % (p["id"], y, exc))
            if data:
                done += 1
    except DailyLimit:
        nxt = (datetime.utcnow() + timedelta(days=1)).replace(hour=0, minute=10, second=0, microsecond=0)
        open(lim, "w").write(nxt.isoformat())
        log("fill: daily archive quota reached after %d files; resuming after %s UTC" % (done, nxt.strftime("%F %H:%M")))
    led["spent"] += spent
    try:
        atomic_write(ledger, led)
    except Exception as exc:
        log("warn: fill ledger: %s" % exc)
    lite, full = build_queue(points, years)
    atomic_write(ROOT + "/data/fill_status.json", {"updated": datetime.now(TZ).isoformat(timespec="seconds"),
                                                   "lite_remaining": len(lite), "full_remaining": len(full)})
    log("fill: fetched %d files; remaining lite %d, full %d" % (done, len(lite), len(full)))
    return done


# ---------------------------------------------------------------- weather database (everything we can keep for analysis)
WX_COLS = ["temp_min_f", "temp_max_f", "temp_mean_f", "rh_mean", "rh_min", "dew_point_f", "vpd_kpa", "precip_in", "rain_in",
           "snowfall_in", "snow_depth_max", "soil_t_shallow_f", "soil_t_mid_f", "soil_t_deep_f", "soil_m_shallow", "soil_m_mid",
           "soil_m_deep", "wind_mph", "pressure_hpa", "cloud_pct", "sw_rad_wm2", "et0_in", "sunshine_h"]


def db_connect():
    os.makedirs(os.path.dirname(DBFILE), exist_ok=True)
    con = sqlite3.connect(DBFILE, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS snapshots (date TEXT, zone TEXT, species TEXT, score INTEGER, label TEXT, "
                "soil_t_7d REAL, precip_14d REAL, PRIMARY KEY (date, zone, species))")
    for col, typ in (("reasons", "TEXT"), ("negatives", "TEXT"), ("confidence", "TEXT"), ("generated_at", "TEXT")):
        try:
            con.execute("ALTER TABLE snapshots ADD COLUMN %s %s" % (col, typ))
        except sqlite3.OperationalError:
            pass
    con.execute("CREATE TABLE IF NOT EXISTS weather_daily (date TEXT, zone TEXT, source TEXT, %s, PRIMARY KEY (date, zone, source))"
                % ", ".join("%s REAL" % c for c in WX_COLS))
    con.execute("CREATE TABLE IF NOT EXISTS live_features (date TEXT, zone TEXT, features TEXT, forecast TEXT, PRIMARY KEY (date, zone))")
    con.execute("CREATE TABLE IF NOT EXISTS burns_seen (date TEXT, name TEXT, year INTEGER, acres REAL, lat REAL, lon REAL, "
                "elev_ft REAL, PRIMARY KEY (date, name, year))")
    con.execute("CREATE TABLE IF NOT EXISTS briefs (date TEXT, scope TEXT, model TEXT, text TEXT, PRIMARY KEY (date, scope))")
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('weather_daily.source_era5', "
                "'Open-Meteo ERA5-Land archive; soil shallow/mid/deep = 0-7/7-28/28-100 cm; temps F, precip in, wind mph')")
    con.execute("INSERT OR REPLACE INTO meta VALUES ('weather_daily.source_forecast', "
                "'Open-Meteo forecast model recent past days (what the live scorer uses); soil shallow/mid/deep = 6/18/54 cm; "
                "moisture shallow/mid/deep = 3-9/9-27/27-81 cm')")
    return con


def _agg(vals, fn):
    v = [x for x in vals if x is not None]
    return fn(v) if v else None


def hourly_to_daily(times, series, daily=None, only_before=None):
    """series: {name: hourly list}. Returns {date: {column: value}} with the right aggregation per column."""
    days = {}
    for i, t in enumerate(times):
        days.setdefault(t.split("T")[0], []).append(i)
    mean = lambda v: sum(v) / len(v)            # noqa: E731
    out = {}
    for d, idx in days.items():
        if only_before and d >= only_before:
            continue
        if len(idx) < 18:                       # partial day
            continue

        def g(name):
            lst = series.get(name) or []
            return [lst[i] for i in idx if i < len(lst)]
        out[d] = {
            "temp_min_f": _agg(g("temp"), min), "temp_max_f": _agg(g("temp"), max), "temp_mean_f": _agg(g("temp"), mean),
            "rh_mean": _agg(g("rh"), mean), "rh_min": _agg(g("rh"), min), "dew_point_f": _agg(g("dew"), mean),
            "vpd_kpa": _agg(g("vpd"), mean), "precip_in": _agg(g("precip"), sum), "rain_in": _agg(g("rain"), sum),
            "snowfall_in": _agg(g("snow"), sum), "snow_depth_max": _agg(g("snowdepth"), max),
            "soil_t_shallow_f": _agg(g("st1"), mean), "soil_t_mid_f": _agg(g("st2"), mean), "soil_t_deep_f": _agg(g("st3"), mean),
            "soil_m_shallow": _agg(g("sm1"), mean), "soil_m_mid": _agg(g("sm2"), mean), "soil_m_deep": _agg(g("sm3"), mean),
            "wind_mph": _agg(g("wind"), mean), "pressure_hpa": _agg(g("pres"), mean), "cloud_pct": _agg(g("cloud"), mean),
            "sw_rad_wm2": _agg(g("sw"), mean), "et0_in": _agg(g("et0"), sum), "sunshine_h": None,
        }
    if daily and daily.get("sunshine_duration"):
        for d, sun in zip(daily.get("time", []), daily["sunshine_duration"]):
            if d in out and sun is not None:
                out[d]["sunshine_h"] = sun / 3600.0
    return out


def store_weather(con, zone_id, source, days):
    rows = [(d, zone_id, source) + tuple(r.get(c) for c in WX_COLS) for d, r in days.items()]
    con.executemany("INSERT OR REPLACE INTO weather_daily VALUES (?,?,?,%s)" % ",".join("?" * len(WX_COLS)), rows)
    return len(rows)


def archive_days(data):
    h, dl = data["hourly"], data["daily"]
    series = {"temp": h.get("temperature_2m"), "rh": h.get("relative_humidity_2m"), "dew": h.get("dew_point_2m"),
              "vpd": h.get("vapour_pressure_deficit"), "snowdepth": h.get("snow_depth"),
              "st1": h.get("soil_temperature_0_to_7cm"), "st2": h.get("soil_temperature_7_to_28cm"),
              "st3": h.get("soil_temperature_28_to_100cm"), "sm1": h.get("soil_moisture_0_to_7cm"),
              "sm2": h.get("soil_moisture_7_to_28cm"), "sm3": h.get("soil_moisture_28_to_100cm"),
              "wind": h.get("wind_speed_10m"), "pres": h.get("surface_pressure"), "cloud": h.get("cloud_cover"),
              "sw": h.get("shortwave_radiation")}
    days = hourly_to_daily(h["time"], series, dl)
    n = len(dl["time"])
    cols = {"precip_in": dl.get("precipitation_sum"), "rain_in": dl.get("rain_sum"), "snowfall_in": dl.get("snowfall_sum"),
            "et0_in": dl.get("et0_fao_evapotranspiration"), "temp_min_f": dl.get("temperature_2m_min"),
            "temp_max_f": dl.get("temperature_2m_max")}
    for col, arr in cols.items():
        if not arr:
            continue
        for d, v in zip(dl["time"], arr):
            if d in days and v is not None:
                days[d][col] = v
    return days


def fetch_recent_model_days(zone):
    """Forecast-model view of the last 7 completed days (the same model family the live scorer uses)."""
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s&past_days=7&forecast_days=1"
           "&hourly=temperature_2m,relative_humidity_2m,dew_point_2m,vapour_pressure_deficit,precipitation,rain,snowfall,"
           "snow_depth,soil_temperature_6cm,soil_temperature_18cm,soil_temperature_54cm,soil_moisture_3_to_9cm,"
           "soil_moisture_9_to_27cm,soil_moisture_27_to_81cm,wind_speed_10m,surface_pressure,cloud_cover,shortwave_radiation,"
           "et0_fao_evapotranspiration&daily=sunshine_duration"
           "&temperature_unit=fahrenheit&precipitation_unit=inch&wind_speed_unit=mph&timezone=America%%2FLos_Angeles"
           % (zone["lat"], zone["lon"]))
    for attempt in range(3):
        try:
            with om_key.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                d = json.loads(r.read().decode())
            h = d["hourly"]
            series = {"temp": h["temperature_2m"], "rh": h["relative_humidity_2m"], "dew": h["dew_point_2m"],
                      "vpd": h["vapour_pressure_deficit"], "precip": h["precipitation"], "rain": h["rain"], "snow": h["snowfall"],
                      "snowdepth": h["snow_depth"], "st1": h["soil_temperature_6cm"], "st2": h["soil_temperature_18cm"],
                      "st3": h["soil_temperature_54cm"], "sm1": h["soil_moisture_3_to_9cm"], "sm2": h["soil_moisture_9_to_27cm"],
                      "sm3": h["soil_moisture_27_to_81cm"], "wind": h["wind_speed_10m"], "pres": h["surface_pressure"],
                      "cloud": h["cloud_cover"], "sw": h["shortwave_radiation"], "et0": h["et0_fao_evapotranspiration"]}
            return hourly_to_daily(h["time"], series, d.get("daily"), only_before=datetime.now(TZ).strftime("%F"))
        except Exception as exc:
            log("warn: recent model days %s: %s" % (zone["id"], exc))
            time.sleep(3 * (attempt + 1))
    return {}


# ---------------------------------------------------------------- live
def run_json(script, *args, timeout=120):
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT + "/omshim" + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")   # routes the skill's Open-Meteo calls through om_key
        p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)] + [str(a) for a in args],
                           capture_output=True, text=True, timeout=timeout, cwd=SCRIPTS, env=env)
        return json.loads(p.stdout)
    except Exception as exc:
        log("warn: %s failed: %s" % (script, exc))
        return None


def slim(w):
    """Scalars only (drops the bulky Aug-1 archive arrays) - this is stored in the database as JSON."""
    return {k: v for k, v in w.items() if isinstance(v, (int, float, str, bool)) or v is None}


FC_CACHE = {"mtime": None, "data": {}}


def _fc_entry(zone):
    """The skill's cached forecast for one point. weather.py rewrites the cache file for every point it fetches, so the file is re-read
    whenever it has changed (reading it once per run would score later points from stale forecasts)."""
    path = SKILL + "/cache/weather_cache.json"
    try:
        mt = os.stat(path).st_mtime_ns
        if mt != FC_CACHE["mtime"]:
            with open(path) as fh:
                FC_CACHE["data"] = json.load(fh)
            FC_CACHE["mtime"] = mt
    except Exception:
        return None
    return FC_CACHE["data"].get("forecast_%s_%s" % (zone["lat"], zone["lon"]))


def merged_inputs(zone, con):
    """Daily inputs from the skill's cached forecast (31 past days + 10 ahead), with past-day rain replaced by ERA5 from the database
    wherever ERA5 exists (it lags about 5 days). The forecast service's "past days" rain can miss real storms badly (Bandon gauge
    1.55 in vs 0.06 in for Oct 20-31 2026) while ERA5 is what the validated history uses. Soil and air temperature are unchanged.
    Returns None when the forecast is not cached."""
    ent = _fc_entry(zone)
    if not ent:
        return None
    d = ent["data"]
    dl = d.get("daily") or {}
    dates = dl.get("time") or []
    if len(dates) < 14:
        return None
    precip = list(dl.get("precipitation_sum") or [])
    ht = d["hourly"]["time"]
    std = daily_means(ht, d["hourly"]["soil_temperature_6cm"])
    smd = daily_means(ht, d["hourly"]["soil_moisture_3_to_9cm"])
    base = len(dates) - 11                              # the skill's "today": last day before the 10-day forecast block
    era5_last = None
    if con is not None:
        try:
            e = dict(con.execute("SELECT date, precip_in FROM weather_daily WHERE zone=? AND source='era5' AND date BETWEEN ? AND ? "
                                 "AND precip_in IS NOT NULL", (zone["id"], dates[0], dates[base])).fetchall())
        except Exception:
            e = {}
        for j in range(base + 1):
            if dates[j] in e:
                precip[j] = e[dates[j]]
                era5_last = dates[j]
    return {"dates": dates, "precip": precip, "tmin": dl.get("temperature_2m_min") or [], "tmax": dl.get("temperature_2m_max") or [],
            "soil_t": [std.get(x) for x in dates], "soil_m": [smd.get(x) for x in dates], "base": base, "era5_last": era5_last}


def season_rain(zone, con, mi):
    """Daily rain from Aug 1 to the skill's "today" for the fall season-opener trigger, in the shape weather.py's archive call returns:
    ERA5 from the database, then the merged forecast-service days. None when the database does not cover most of the period, so the
    caller keeps whatever weather.py fetched. This removes the live scores' dependence on the free archive quota."""
    if con is None or not mi:
        return None
    end = mi["dates"][mi["base"]]
    start = end[:4] + "-08-01"
    if end < start:
        return None
    try:
        e = dict(con.execute("SELECT date, precip_in FROM weather_daily WHERE zone=? AND source='era5' AND date BETWEEN ? AND ? "
                             "AND precip_in IS NOT NULL", (zone["id"], start, end)).fetchall())
    except Exception:
        return None
    mp = dict(zip(mi["dates"][:mi["base"] + 1], mi["precip"][:mi["base"] + 1]))
    times, pr, have = [], [], 0
    d = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while d <= last:
        k = d.isoformat()
        if k in e:
            v = e[k]; have += 1
        elif k in mp and mp[k] is not None:
            v = mp[k]; have += 1
        else:
            v = 0.0
        times.append(k); pr.append(v)
        d += timedelta(days=1)
    if have < 0.9 * len(times):
        return None
    return {"daily": {"time": times, "precipitation_sum": pr}}


def forecast_scores(reg, zone, sp_keys, w, month, days=7, con=None):
    """Scores for today and the next days-1 days, from the same inputs the live card uses (merged_inputs: the skill's cached forecast,
    past-day rain from ERA5 where available). Day 0 reproduces the live score. {} on any problem."""
    try:
        mi = merged_inputs(zone, con)
        if not mi:
            return {}
        dates, precip, tmin, tmax, soil_t, soil_m, base = (mi["dates"], mi["precip"], mi["tmin"], mi["tmax"], mi["soil_t"],
                                                           mi["soil_m"], mi["base"])
        out = {k: [] for k in sp_keys}
        arch = w.get("archive_data") or {}
        for off in range(days):
            i = base + off
            if i >= len(dates):
                break
            day_utc = datetime.utcnow().date() + timedelta(days=off)
            day_loc = datetime.now(TZ).date() + timedelta(days=off)
            f = features_at(i, dates, precip, tmin, tmax, soil_t, soil_m)
            if w.get("melt_out_date"):
                f["melt_out_date"] = w["melt_out_date"]
            if arch.get("daily"):
                ad = arch["daily"]
                times, pr = list(ad.get("time") or []), list(ad.get("precipitation_sum") or [])
                last = times[-1] if times else ""
                for j in range(len(dates)):
                    if dates[j] > last and dates[j] <= day_utc.isoformat():
                        times.append(dates[j])
                        pr.append(precip[j] or 0)
                f["archive_data"] = {"daily": {"time": times, "precipitation_sum": pr}}
            f["data_timestamp"] = w.get("data_timestamp")
            FakeDT._now = datetime(day_utc.year, day_utc.month, day_utc.day, 12)
            sc.datetime = FakeDT
            for k in sp_keys:
                r = sc.score_species(reg_for(reg, zone), k, zone, day_loc.month if off else month, f)
                out[k].append(None if r["label"] == "gated out" else r["score"])
        return out
    except Exception as exc:
        log("warn: forecast scores %s: %s" % (zone.get("id"), exc))
        return {}
    finally:
        sc.datetime = datetime



def build_live(reg, points, con=None, burns=True):
    now = datetime.now(TZ)
    month, year = now.month, now.year
    today = now.strftime("%F")
    live = {"generated_at": now.isoformat(timespec="seconds"), "zones": {}, "burns": [], "burns_note": ""}
    rows = []
    for z in points:
        sp = [k for k in zone_species(reg, z) if species_in_window(reg, k, z, month)]
        entry = {"species": {}, "forecast": None, "data_timestamp": None}
        if sp:
            w = run_json("weather.py", z["lat"], z["lon"], month)
            if w and "error" not in w:
                if 3 <= month <= 7 and z["elev_ft"] >= 3500 and any(k in ("morel_natural", "king_spring") for k in sp):
                    s = run_json("snotel.py", z["lat"], z["lon"], year)
                    if s and s.get("melt_out_date"):
                        w["melt_out_date"] = s["melt_out_date"]
                mi = merged_inputs(z, con)                       # past-day rain from ERA5 where the database has it (see merged_inputs)
                if mi:
                    f0 = features_at(mi["base"], mi["dates"], mi["precip"], mi["tmin"], mi["tmax"], mi["soil_t"], mi["soil_m"])
                    for fk in ("precip_7d", "precip_14d", "precip_30d", "last_rain_event"):
                        w[fk] = f0[fk]
                    entry["rain_era5_through"] = mi["era5_last"]
                    if month >= 8:                               # season-opener rain since Aug 1 from the database, not a second free-API call
                        ad = season_rain(z, con, mi)
                        if ad:
                            w["archive_data"] = ad
                entry["data_timestamp"] = w.get("data_timestamp")
                entry["forecast"] = {"rain_10d_in": round(w.get("forecast_precip_10d") or 0, 2),
                                     "daily_high_lowest_f": w.get("forecast_temp_min_10d"),   # NB: skill's "min" is the lowest daily HIGH
                                     "daily_high_highest_f": w.get("forecast_temp_max_10d")}
                if con is not None:
                    con.execute("INSERT OR REPLACE INTO live_features VALUES (?,?,?,?)",
                                (today, z["id"], json.dumps(slim(w)), json.dumps(entry["forecast"])))
                for k in sp:
                    r = sc.score_species(reg_for(reg, z), k, z, month, w)
                    if r["label"] == "gated out":
                        continue
                    entry["species"][k] = {"score": r["score"], "label": r["label"].split(" - ")[0], "reasons": r["reasons"][:4],
                                           "negatives": r["negatives"][:2], "confidence": r["confidence"]}
                    rows.append((today, z["id"], k, r["score"], r["label"].split(" - ")[0], w.get("soil_t_7d_mean"),
                                 w.get("precip_14d"), json.dumps(r["reasons"]), json.dumps(r["negatives"]),
                                 str(r["confidence"]), now.isoformat(timespec="seconds")))
                fcs = forecast_scores(reg, z, [k for k in sp if k in entry["species"]], w, month, con=con)
                for k, arr in fcs.items():
                    if arr and arr[0] is not None and abs(arr[0] - entry["species"][k]["score"]) > 2:
                        log("note: forecast day-0 score differs from live for %s %s: %s vs %s" % (z["id"], k, arr[0], entry["species"][k]["score"]))
                    entry["species"][k]["fc"] = arr
                if fcs:
                    entry["fc_start"] = datetime.now(TZ).strftime("%F")
            time.sleep(0.4)
        live["zones"][z["id"]] = entry
    if burns and 4 <= month <= 6:
        f = run_json("fires.py", 44.0, -121.5, 450)
        for x in (f or {}).get("fires", [])[:40]:
            live["burns"].append({"name": x["name"], "year": x["year"], "acres": x["acres"], "lat": x["centroid_lat"],
                                  "lon": x["centroid_lon"], "elev_ft": x.get("elev_ft")})
            if con is not None:
                con.execute("INSERT OR REPLACE INTO burns_seen VALUES (?,?,?,?,?,?,?)",
                            (today, x["name"], x["year"], x["acres"], x["centroid_lat"], x["centroid_lon"], x.get("elev_ft")))
        live["burns_note"] = "Burned snags kill people in wind; check the forest's closure orders before driving."
    return live, rows


def outlook(per, doy0, s0, horizons=(7, 14), window=10, tol=10):
    """History-based outlook: on past days within +-window days of today's date whose score was within +-tol of today's,
    what was the score `h` days later? Returns {'d7': {med,p25,p75,p60,n,years}, ...} or {} when there are too few analogs."""
    cur = datetime.now(TZ).year
    res = {h: [] for h in horizons}
    yrs = {h: set() for h in horizons}
    for y, arr in per.items():
        if int(y) >= cur:
            continue
        for d in range(max(0, doy0 - window), min(365, doy0 + window) + 1):
            v = arr[d]
            if v is None or abs(v - s0) > tol:
                continue
            for h in horizons:
                if d + h < len(arr) and arr[d + h] is not None:
                    res[h].append(arr[d + h])
                    yrs[h].add(y)
    out = {}
    for h, v in res.items():
        if len(v) >= 15 and len(yrs[h]) >= 3:
            s = sorted(v)
            out["d%d" % h] = {"med": s[len(s) // 2], "p25": s[len(s) // 4], "p75": s[(3 * len(s)) // 4],
                              "p60": round(100.0 * sum(1 for x in s if x >= 60) / len(s)), "n": len(s), "years": len(yrs[h])}
    return out


def attach_outlook(live, allseries):
    today = datetime.now(TZ).date()
    doy0 = (today - date(today.year, 1, 1)).days
    for zid, e in live["zones"].items():
        o = {}
        for k, r in e["species"].items():
            per = allseries.get("%s|%s" % (zid, k))
            if per:
                x = outlook(per, doy0, r["score"])
                if x:
                    o[k] = x
        if o:
            e["outlook"] = o


def store_snapshot(con, rows):
    con.executemany("INSERT OR REPLACE INTO snapshots (date, zone, species, score, label, soil_t_7d, precip_14d, reasons, "
                    "negatives, confidence, generated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    return con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


def export_snapshots(con):
    """Compact public export of the nightly live scores (listed zones only) for the site's 'live record' charts."""
    out = {}
    for d, z, sp, score in con.execute("SELECT date, zone, species, score FROM snapshots WHERE zone NOT LIKE 'g\\_%' ESCAPE '\\' ORDER BY date"):
        out.setdefault("%s|%s" % (z, sp), []).append([d, score])
    st = {
        "snapshots": con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        "snapshot_days": con.execute("SELECT COUNT(DISTINCT date) FROM snapshots").fetchone()[0],
        "weather_rows": con.execute("SELECT COUNT(*) FROM weather_daily").fetchone()[0],
        "weather_first": con.execute("SELECT MIN(date) FROM weather_daily").fetchone()[0],
        "weather_last": con.execute("SELECT MAX(date) FROM weather_daily").fetchone()[0],
        "weather_vars": len(WX_COLS),
        "zones_with_weather": con.execute("SELECT COUNT(DISTINCT zone) FROM weather_daily WHERE zone NOT LIKE 'g\\_%' ESCAPE '\\'").fetchone()[0],
        "sample_points_with_weather": con.execute("SELECT COUNT(DISTINCT zone) FROM weather_daily WHERE zone LIKE 'g\\_%' ESCAPE '\\'").fetchone()[0],
    }
    atomic_write(SITE_DATA + "/snapshots.json", {"generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
                                                 "stats": st, "series": out})
    return st


def write_grid(grid, gseries, glive, years):
    """Unlisted sample points that exist only to make the heat map: current scores (+ history-based outlook) and a thinned history."""
    miss = sum(1 for g in grid for y in years if source_path(g, y) is None)
    cov = {"lite_remaining": miss, "lite_total": len(grid) * len(years)}
    pts = []
    prev = {}
    if glive is None:                                   # rebuild without a nightly run: keep the last live scores
        try:
            prev = {p["id"]: p["live"] for p in json.load(open(SITE_DATA + "/grid.json"))["points"]}
        except Exception:
            prev = {}
    for g in grid:
        e = (glive or {}).get("zones", {}).get(g["id"], {})
        sp = dict(prev.get(g["id"], {}))
        for k, r in e.get("species", {}).items():
            o = e.get("outlook", {}).get(k, {})
            sp[k] = {"s": r["score"], "o7": [o["d7"]["med"], o["d7"]["p25"], o["d7"]["p75"]] if "d7" in o else None,
                     "o14": [o["d14"]["med"], o["d14"]["p25"], o["d14"]["p75"]] if "d14" in o else None}
        pts.append({"id": g["id"], "lat": g["lat"], "lon": g["lon"], "elev_ft": g["elev_ft"], "side": g["side"], "live": sp})
    atomic_write(SITE_DATA + "/grid.json", {
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"), "points": pts,
        "note": "Unlisted sample points (about 35 km apart) used only to draw the heat map. Each is scored with the same model at the point's own elevation.",
        "coverage": cov})
    step = 3
    atomic_write(SITE_DATA + "/grid_hist.json", {"step": step, "years": years, "series": {
        k: {y: arr[::step] for y, arr in per.items()} for k, per in gseries.items()}})


# ---------------------------------------------------------------- public weather exports (derived from the database)
WX_ROUND = {"temp_min_f": 1, "temp_max_f": 1, "temp_mean_f": 1, "rh_mean": 0, "rh_min": 0, "dew_point_f": 1, "vpd_kpa": 2,
            "precip_in": 2, "rain_in": 2, "snowfall_in": 2, "snow_depth_max": 2, "soil_t_shallow_f": 1, "soil_t_mid_f": 1,
            "soil_t_deep_f": 1, "soil_m_shallow": 3, "soil_m_mid": 3, "soil_m_deep": 3, "wind_mph": 1, "pressure_hpa": 0,
            "cloud_pct": 0, "sw_rad_wm2": 0, "et0_in": 3, "sunshine_h": 1}
MAP_COLS = {"soil_t_shallow_f": 10, "soil_m_shallow": 1000, "rh_mean": 1, "vpd_kpa": 100, "precip_in": 100, "temp_max_f": 1}
WX_START = "2015-12-01"


def zone_weather(con, zone_id):
    """{date: {col: value}} - ERA5 rows win, forecast-model rows fill the most recent days the reanalysis does not have yet."""
    days = {}
    for src in ("forecast", "era5"):
        cur = con.execute("SELECT date, %s FROM weather_daily WHERE zone=? AND source=? ORDER BY date" % ", ".join(WX_COLS),
                          (zone_id, src))
        for row in cur:
            days[row[0]] = dict(zip(WX_COLS, row[1:]))
    return days


def export_weather(con, zones):
    d0 = date.fromisoformat(WX_START)
    wxmap = {"start": WX_START, "scale": MAP_COLS, "zones": {}}
    last_day = None
    for z in zones:
        days = zone_weather(con, z["id"])
        if not days:
            continue
        last = max(days)
        last_day = max(last_day or last, last)
        n = (date.fromisoformat(last) - d0).days + 1
        cols = {c: [None] * n for c in WX_COLS}
        for ds, row in days.items():
            i = (date.fromisoformat(ds) - d0).days
            if 0 <= i < n:
                for c in WX_COLS:
                    v = row.get(c)
                    if v is not None:
                        cols[c][i] = round(v, WX_ROUND[c]) if WX_ROUND[c] else int(round(v))
        atomic_write("%s/wx/%s.json" % (SITE_DATA, z["id"]), {"start": WX_START, "last": last, "cols": WX_COLS, "d": cols,
                                                              "note": "Daily values. Soil layers: ERA5-Land 0-7/7-28/28-100 cm (forecast-model 6/18/54 cm for the newest days)."})
        wxmap["zones"][z["id"]] = {c: [None if v is None else int(round(v * k)) for v in cols[c]] for c, k in MAP_COLS.items()}
    wxmap["last"] = last_day
    atomic_write(SITE_DATA + "/wxmap.json", wxmap)


def pctile(vals, p):
    s = sorted(vals)
    return s[min(len(s) - 1, int(p * len(s)))]


def export_insights(con, series, zones):
    """What the weather looks like on 'prime' (score >= 60) days vs other in-season days, per species, across all zones."""
    vars_ = ["soil_t_shallow_f", "soil_t_mid_f", "soil_m_shallow", "soil_m_mid", "soil_m_deep", "rh_mean", "vpd_kpa",
             "temp_max_f", "temp_min_f", "cloud_pct", "wind_mph", "sw_rad_wm2", "dew_point_f"]
    wx = {z["id"]: zone_weather(con, z["id"]) for z in zones}
    acc = {}
    for key, per in series.items():
        zid, sp = key.split("|")
        for y, arr in per.items():
            jan1 = date(int(y), 1, 1)
            for i, v in enumerate(arr):
                if v is None:
                    continue
                row = wx.get(zid, {}).get((jan1 + timedelta(days=i)).isoformat())
                if not row:
                    continue
                grp = "prime" if v >= 60 else "other"
                for c in vars_:
                    if row.get(c) is not None:
                        acc.setdefault(sp, {}).setdefault(c, {"prime": [], "other": []})[grp].append(row[c])
    out = {}
    for sp, byvar in acc.items():
        out[sp] = {}
        for c, groups in byvar.items():
            out[sp][c] = {g: ({"n": len(v), "p25": round(pctile(v, .25), 3), "med": round(pctile(v, .5), 3), "p75": round(pctile(v, .75), 3)}
                              if len(v) >= 20 else None) for g, v in groups.items()}
    atomic_write(SITE_DATA + "/insights.json", {"generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
                                                "prime_threshold": 60, "species": out,
                                                "note": "Weather on days the model scores 60+ vs other in-season days, pooled over all zones and years."})


# ---------------------------------------------------------------- compact datasets for the redesigned front end (site/data/c/*.json)
def export_compact():
    """Flattens the site's JSON into the row-oriented files the redesigned page reads. Reads what the builder just wrote."""
    def rd(name):
        return json.load(open("%s/%s.json" % (SITE_DATA, name)))
    zones, live, grid, hist = rd("zones"), rd("live"), rd("grid"), rd("history")
    try:
        wx = rd("wxmap")
    except Exception:
        wx = {"zones": {}, "scale": {}, "last": None}
    try:
        gh = rd("grid_hist")
    except Exception:
        gh = {"series": {}, "step": 3}
    out = SITE_DATA + "/c"
    os.makedirs(out, exist_ok=True)

    def fam(k):
        return "morel" if k.startswith("morel") else k

    zrows = []
    for z in zones["zones"]:
        zrows.append({"id": z["id"], "name": z["name"], "lat": z["lat"], "lon": z["lon"], "elev_ft": z["elev_ft"], "side": z.get("side"),
                      "land": z.get("land", ""), "habitat": z.get("habitat", ""), "permit": (z.get("permit") or {}).get("text", ""),
                      "permit_verify": bool((z.get("permit") or {}).get("verify_before_you_go")), "pdx_km": z.get("pdx_km"),
                      "pdx_drive_h": z.get("pdx_drive_h"), "regions": ",".join(z.get("regions") or []),
                      "species": ",".join(s["key"] for s in z["species"])})
    atomic_write(out + "/zones.json", zrows)

    srows = []
    for z in zones["zones"]:
        lz = live["zones"].get(z["id"], {})
        fc = lz.get("forecast") or {}
        for s in z["species"]:
            r = (lz.get("species") or {}).get(s["key"])
            o = ((lz.get("outlook") or {}).get(s["key"])) or {}
            fcv = (r or {}).get("fc") or []
            row = {"zone": z["id"], "species": s["key"], "display": s["display"], "family": fam(s["key"]),
                   "rain_era5_through": lz.get("rain_era5_through"),
                   "fc_start": lz.get("fc_start") if fcv else None, "fc": ",".join("" if v is None else str(v) for v in fcv),
                   "score": r["score"] if r else None, "label": r["label"] if r else "off-season",
                   "confidence": r.get("confidence") if r else None,
                   "reasons": " | ".join(r["reasons"]) if r else "", "negatives": " | ".join(r["negatives"]) if r else "",
                   "rain_10d_in": fc.get("rain_10d_in"), "hi_low_f": fc.get("daily_high_lowest_f"), "hi_high_f": fc.get("daily_high_highest_f")}
            for hz in ("d7", "d14"):
                d = o.get(hz) or {}
                for f in ("med", "p25", "p75", "p60", "n", "years"):
                    row["%s_%s" % (hz, f)] = d.get(f)
            srows.append(row)
    atomic_write(out + "/live.json", srows)

    hrows = []
    for key, yrs in hist["series"].items():
        zid, sk = key.split("|")
        for y, arr in yrs.items():
            hrows.append({"series": key, "zone": zid, "species": sk, "year": int(y), "scores": ",".join("" if v is None else str(v) for v in arr)})
    atomic_write(out + "/history.json", hrows)

    sc_ = wx.get("scale", {})
    wrows = []

    def val(zid, col):
        a = wx["zones"].get(zid, {}).get(col)
        if not a or a[-1] is None or not sc_.get(col):
            return None
        return a[-1] / sc_[col]
    for z in zones["zones"]:
        zid = z["id"]
        if zid not in wx.get("zones", {}):
            continue
        p = wx["zones"][zid].get("precip_in") or []
        k = sc_.get("precip_in") or 100
        wrows.append({"zone": zid, "asof": wx.get("last"), "soil_t_f": val(zid, "soil_t_shallow_f"),
                      "soil_m_pct": (val(zid, "soil_m_shallow") or 0) * 100, "rh_pct": val(zid, "rh_mean"), "vpd_kpa": val(zid, "vpd_kpa"),
                      "tmax_f": val(zid, "temp_max_f"), "rain14_in": round(sum((x or 0) for x in p[-14:]) / k, 2),
                      "rain30_in": round(sum((x or 0) for x in p[-30:]) / k, 2)})
    atomic_write(out + "/weather.json", wrows)

    grows = []
    for p in grid["points"]:
        if not p["live"]:
            grows.append({"id": p["id"], "lat": p["lat"], "lon": p["lon"], "elev_ft": p["elev_ft"], "side": p["side"], "species": None,
                          "score": None, "o7": None, "o14": None})
        for k, v in p["live"].items():
            grows.append({"id": p["id"], "lat": p["lat"], "lon": p["lon"], "elev_ft": p["elev_ft"], "side": p["side"], "species": k,
                          "score": v.get("s"), "o7": (v.get("o7") or [None])[0], "o14": (v.get("o14") or [None])[0]})
    atomic_write(out + "/grid.json", grows)

    ghrows = []
    for key, yrs in gh["series"].items():
        gid, sk = key.split("|")
        for y, arr in yrs.items():
            ghrows.append({"id": gid, "species": sk, "year": int(y), "scores": ",".join("" if v is None else str(v) for v in arr)})
    atomic_write(out + "/grid_hist.json", ghrows)

    brief = live.get("brief") or {}
    atomic_write(out + "/about.json", [{
        "generated_at": live["generated_at"], "history_years": ",".join(map(str, hist["years"])), "source": hist["source"], "caveat": hist["caveat"],
        "fine_print": zones["fine_print"], "permits_note": zones.get("permits_note", ""), "weather_last": wx.get("last"),
        "band_labels": json.dumps(hist.get("labels", [])), "brief_text": brief.get("text"), "brief_note": brief.get("note"),
        "brief_date": brief.get("date"), "grid_step": gh.get("step", 3), "grid_remaining": (grid.get("coverage") or {}).get("lite_remaining", 0)}])


# ---------------------------------------------------------------- orchestration
def write_history(series, years, reg):
    years_all = sorted({int(y) for per in series.values() for y in per})
    atomic_write(SITE_DATA + "/history.json", {
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "years": years_all,
        "source": "Open-Meteo ERA5-Land archive (reanalysis), scored with the oregon-mushroom-scout model",
        "caveat": ("History is a model reconstruction from weather reanalysis, not observed mushrooms. Live scores use a forecast "
                   "model whose soil temperature differs slightly from the reanalysis."),
        "labels": reg.get("score_labels", []),
        "series": series})


def load_series_cache():
    try:
        return json.load(open(ROOT + "/data/series.json"))
    except Exception:
        return {}


def all_zones():
    base = sc.load_zones()
    zx, px = load_extras()
    ids = {z["id"] for z in base}
    extra = [z for z in zx["zones"] if z["id"] not in ids]
    return base + extra, zx, px


def write_zones(reg, zones, perms, zx, px, series):
    atomic_write(SITE_DATA + "/zones.json", {
        "zones": build_zones(reg, zones, perms, zx, px, series), "fine_print": FINE_PRINT,
        "regions": zx.get("regions", {}), "pdx": {"lat": PDX[0], "lon": PDX[1]},
        "permits_note": "Permit text comes from a compiled file and Forest Service pages (see 'verify before you go'); rules change."})


def load_grid():
    try:
        return json.load(open(ROOT + "/data/grid.json"))["points"]
    except Exception:
        return []


def attach_zone_outlook_public(live):
    """Nothing private is in live.json; outlook per zone/species is already attached by attach_outlook()."""
    return live


def rebuild_all(reg, perms, zones, grid, zx, px, years, con, net_cur=False):
    pts = zones + grid
    allser = run_backfill(reg, pts, years, con, net_cur)
    series = prune_series({k: v for k, v in allser.items() if not k.startswith("g_")})
    gseries = prune_series({k: v for k, v in allser.items() if k.startswith("g_")})
    atomic_write(ROOT + "/data/series.json", series)
    write_history(series, years, reg)
    write_zones(reg, zones, perms, zx, px, series)
    export_weather(con, zones)
    export_insights(con, series, zones)
    return series, gseries, allser


def archive_ok():
    """True unless the free archive API says its daily or hourly limit is used up (one tiny request). Network trouble counts as OK."""
    d = (datetime.utcnow() - timedelta(days=7)).strftime("%F")
    url = "https://archive-api.open-meteo.com/v1/archive?latitude=44.0&longitude=-122.0&start_date=%s&end_date=%s&daily=temperature_2m_max" % (d, d)
    try:
        om_key.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        return True, ""
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            try:
                return False, exc.read().decode()[:90]
            except Exception:
                return False, "HTTP 429"
        return True, ""
    except Exception:
        return True, ""


def sight_pending():
    """True while past-find records still need a land class (the hourly auto run then finishes the tagging)."""
    try:
        import shrooms_sightings
        return shrooms_sightings.pending(db_connect()) > 0
    except Exception:
        return False


def lock_or_exit():
    try:
        import fcntl
    except ImportError:                                         # non-Linux (local testing only)
        return None
    fh = open(ROOT + "/data/build.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another build is running; exiting")
        raise SystemExit(0)
    return fh


def main():
    argv = sys.argv[1:]
    mode = argv[0] if argv else "auto"
    reg, perms = sc.load_registry(), load_permits()
    zones, zx, px = all_zones()
    grid = load_grid()
    cur = datetime.now(TZ).year
    years = list(range(2016, cur + 1))
    if "--years" in argv:
        a, b = argv[argv.index("--years") + 1].split("-")
        years = list(range(int(a), int(b) + 1))
    minutes = int(argv[argv.index("--minutes") + 1]) if "--minutes" in argv else 50
    if "--only" in argv:                                        # testing: restrict to some point ids
        keep = set(argv[argv.index("--only") + 1].split(","))
        zones = [z for z in zones if z["id"] in keep]
        grid = [g for g in grid if g["id"] in keep]

    if mode == "zones":
        write_zones(reg, zones, perms, zx, px, load_series_cache())
        return 0
    os.makedirs(ROOT + "/data", exist_ok=True)
    lock = lock_or_exit()                                       # noqa: F841  (held for the life of the process)
    if mode == "auto":
        now = datetime.now(TZ)
        flag = ROOT + "/data/last_nightly"
        due = now.hour >= 6 and not (os.path.exists(flag) and open(flag).read().strip() == now.strftime("%F"))
        if due:
            ok, why = archive_ok()
            if not ok:                                          # weather.py's season-opener call would fail and fall scores would drop
                log("nightly: waiting, the free archive quota is used up (%s); retrying next hour" % why)
                return 0
            mode = "nightly"
        else:
            lite, full = build_queue(zones + grid, years)
            if lite or full:
                mode = "fill"
            elif sight_pending():
                mode = "sightings"
            else:
                return 0
    con = db_connect()
    if mode == "sightings":                                     # past finds + land tagging only (see shrooms_sightings.py)
        import shrooms_sightings
        shrooms_sightings.run(con, SITE_DATA, full="--full" in argv, minutes=minutes, log=log)
        return 0
    if mode in ("backfill", "rebuild", "fill"):
        if mode in ("backfill", "fill"):
            run_fill(zones + grid, years, con, minutes, "--lite-only" in argv)
        series, gseries, allser = rebuild_all(reg, perms, zones, grid, zx, px, years, con)
        write_grid(grid, gseries, None, years)
        st = export_snapshots(con)
        try:
            export_compact()
        except Exception as exc:
            log("warn: compact export failed: %r" % exc)
        log("%s done: %d zone series, %d grid series, weather rows %d" % (mode, len(series), len(gseries), st["weather_rows"]))
        return 0
    if mode == "live":                                          # manual: refresh live scores + forecast days for the listed zones only (no history rebuild)
        try:
            ser = load_series_cache()
            live, rows = build_live(reg, zones, con)
            attach_outlook(live, ser)
            store_snapshot(con, rows)
            br = None
            try:                                                # rescored, so write a fresh brief from the new numbers
                import shrooms_brief
                br = shrooms_brief.make_brief(live, zones, con, log, force=True)
            except Exception as exc:
                log("note: brief skipped: %r" % exc)
            if not br:                                          # no fresh brief: keep the earlier one, flagged as older than the scores
                try:
                    br = json.load(open(SITE_DATA + "/live.json")).get("brief")
                    if br:
                        br = dict(br)
                        if "refreshed since" not in (br.get("note") or ""):
                            br["note"] = (br.get("note") or "") + " Scores have been refreshed since it was written."
                except Exception:
                    br = None
            live["brief"] = br
            atomic_write(SITE_DATA + "/live.json", live)
            export_compact()
            log("live done: %d zones, forecast days attached to %d" % (len(live["zones"]), sum(1 for e in live["zones"].values() if e.get("fc_start"))))
            return 0
        except Exception as exc:
            log("ERROR live: %r" % exc)
            return 1
    if mode == "nightly":
        try:
            run_fill_quick = False                              # (the archive tail is extended inside rebuild_all via net_cur)
            series, gseries, allser = rebuild_all(reg, perms, zones, grid, zx, px, years, con, net_cur=True)
            for z in zones + grid:                              # forecast-model view of the last 7 days (consistent with live scores)
                store_weather(con, z["id"], "forecast", fetch_recent_model_days(z))
                time.sleep(0.3)
            con.commit()
            live, rows = build_live(reg, zones + grid, con)
            attach_outlook(live, allser)
            scored = sum(len(z["species"]) for z in live["zones"].values())
            n = store_snapshot(con, rows)
            glive = {"zones": {g["id"]: live["zones"].pop(g["id"]) for g in grid if g["id"] in live["zones"]}}
            try:
                import shrooms_brief                                # optional AI narrative, see /opt/shrooms/shrooms_brief.py
                live["brief"] = shrooms_brief.make_brief(live, zones, con, log)
            except ImportError:
                pass
            except Exception as exc:
                log("note: brief skipped: %r" % exc)
            atomic_write(SITE_DATA + "/live.json", live)
            write_grid(grid, gseries, glive, years)
            st = export_snapshots(con)
            try:
                import shrooms_sightings
                shrooms_sightings.run(con, SITE_DATA, minutes=15, log=log)
            except ImportError:
                pass
            except Exception as exc:
                log("note: sightings update skipped: %r" % exc)
            export_compact()
            open(ROOT + "/data/last_nightly", "w").write(datetime.now(TZ).strftime("%F"))
            log("nightly done: %d live scores, snapshot rows %d, weather rows %d" % (scored, n, st["weather_rows"]))
            kuma_push("up", "nightly build ok: %d live scores, %d series, wx rows %d" % (scored, len(series) + len(gseries), st["weather_rows"]))
            return 0
        except Exception as exc:
            log("ERROR nightly: %r" % exc)
            kuma_push("down", "nightly build FAILED: %r" % exc)
            return 1
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
