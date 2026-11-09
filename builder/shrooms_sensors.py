"""Live readings from public soil and rain sensors near each zone, for context in the zone panel (not used in the score).
NRCS SNOTEL (forest clearings; report generator CSV, start-of-day values) and Bureau of Reclamation AgriMet (valley, coast and east-side
fields; 15-minute data averaged by day). Station list: site/data/c/sensors.json (built by analysis/sensors_build.py). Public domain data,
no keys. Writes site/data/c/sensors_live.json. Called by the nightly build; never raises into it. Stdlib only.
"""
import csv, io, json, math, time, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "shrooms.strong.beer (nightly sensor readings)"}
MAX_KM = 45.0
MAX_ELEV_DIFF_FT = 2000


def _get(url):
    for a in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode()
        except Exception:
            time.sleep(4 * (a + 1))
    return None


def _rows(text):
    return [r for r in csv.reader(io.StringIO("\n".join(l for l in (text or "").splitlines() if not l.startswith("#")))) if r]


def _hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def snotel(st, start, end):
    """{date: (soil_4in_F, precip_increment_in)} from the NRCS report generator."""
    depth = int(st["depth_a"].split()[0]) if st.get("depth_a") else 4
    url = ("https://wcc.sc.egov.usda.gov/reportGenerator/view_csv/customSingleStationReport/daily/%s%%7Cid=%%22%%22%%7Cname/%s,%s/"
           "STO:-%d:value,PRCP::value" % (st["id"], start, end, depth))
    out = {}
    for r in _rows(_get(url))[1:]:
        try:
            out[r[0]] = (float(r[1]) if r[1] != "" else None, float(r[2]) if len(r) > 2 and r[2] != "" else None)
        except ValueError:
            pass
    return out


def agrimet(st, start, end):
    """{date: (soil_F daily mean, precip_in)}: soil from 15-minute readings, rain from the daily report."""
    s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
    pc = "sw" if st.get("depth_a") else "sv"
    soil = defaultdict(list)
    t = _get("https://www.usbr.gov/pn-bin/instant.pl?station=%s&format=csv&year=%d&month=%d&day=%d&year=%d&month=%d&day=%d&pcode=%s"
             % (st["id"], s.year, s.month, s.day, e.year, e.month, e.day, pc))
    for r in _rows(t)[1:]:
        if len(r) > 1 and r[1] != "":
            try:
                soil[r[0][:10]].append(float(r[1]))
            except ValueError:
                pass
    rain = {}
    t = _get("https://www.usbr.gov/pn-bin/daily.pl?station=%s&format=csv&year=%d&month=%d&day=%d&year=%d&month=%d&day=%d&pcode=pp"
             % (st["id"], s.year, s.month, s.day, e.year, e.month, e.day))
    for r in _rows(t)[1:]:
        if len(r) > 1 and r[1].strip() != "":
            try:
                v = float(r[1])
                if 0 <= v < 20:                        # the feed uses large negative numbers for missing days
                    rain[r[0]] = v
            except ValueError:
                pass
    days = set(soil) | set(rain)
    return {d: (sum(soil[d]) / len(soil[d]) if len(soil.get(d, [])) >= 80 else None, rain.get(d)) for d in days}


def run(zones, site_data, log=print):
    try:
        stations = json.load(open(site_data + "/c/sensors.json"))["stations"]
    except Exception as exc:
        log("sensors: no station list (%s)" % exc)
        return
    end = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%F")
    start = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%F")
    pick = {}
    for z in zones:
        best = None
        for st in stations:
            dk = _hav(z["lat"], z["lon"], st["lat"], st["lon"])
            if dk <= MAX_KM and abs((st.get("elev_ft") or 0) - z["elev_ft"]) <= MAX_ELEV_DIFF_FT and (best is None or dk < best[0]):
                best = (dk, st)
        if best:
            pick[z["id"]] = best
    data = {}
    for st in {id(v[1]): v[1] for v in pick.values()}.values():
        try:
            data[st["id"]] = snotel(st, start, end) if st["net"] == "SNOTEL" else agrimet(st, start, end)
        except Exception as exc:
            log("sensors: %s failed: %r" % (st["name"], exc))
        time.sleep(0.5)
    out = {}
    for zid, (dk, st) in pick.items():
        d = data.get(st["id"]) or {}
        soil = [(k, v[0]) for k, v in sorted(d.items()) if v[0] is not None]
        rain = [v[1] for k, v in sorted(d.items()) if v[1] is not None][-7:]
        if not soil and not rain:
            continue
        out[zid] = {"station": st["name"], "net": st["net"], "kind": st.get("kind"), "dist_km": round(dk), "elev_ft": st.get("elev_ft"),
                    "depth": st.get("depth_a") or st.get("depth_b"),
                    "soil_f": round(soil[-1][1], 1) if soil else None, "soil_date": soil[-1][0] if soil else None,
                    "rain_7d_in": round(sum(rain), 2) if len(rain) >= 5 else None}
    tmp = site_data + "/c/sensors_live.json.tmp"
    json.dump({"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "zones": out}, open(tmp, "w"), separators=(",", ":"))
    import os
    os.replace(tmp, site_data + "/c/sensors_live.json")
    log("sensors: readings for %d of %d zones from %d stations" % (len(out), len(zones), len(data)))
