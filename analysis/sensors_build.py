"""Builds data/c/sensors.json for the Stats tab: measured soil temperature (NRCS SNOTEL and Bureau of Reclamation AgriMet, public domain) as weekly
means for 2022-2025, next to the model's soil temperature (ERA5-Land layers) for the same weeks. Aggregate only.
usage: python sensors_build.py sto_data.json sno_era5_cache.json out.json"""
import csv, io, json, os, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import date

sto = json.load(open(sys.argv[1]))
snocache = json.load(open(sys.argv[2]))
OUT = sys.argv[3]
YEARS = [2022, 2023, 2024, 2025]
UA = {"User-Agent": "shrooms-validation/1.0"}
AMC = "am_era5_cache.json"
amcache = json.load(open(AMC)) if os.path.exists(AMC) else {}


def wk(d):
    return min(52, (date.fromisoformat(d) - date(int(d[:4]), 1, 1)).days // 7)


def weekly(daily):                      # {date: value} -> {year: [53 weekly means or None]}
    acc = {y: [[] for _ in range(53)] for y in YEARS}
    for d, v in daily.items():
        if v is None or int(d[:4]) not in acc:
            continue
        acc[int(d[:4])][wk(d)].append(v)
    return {str(y): [round(sum(a) / len(a), 1) if len(a) >= 3 else None for a in arr] for y, arr in acc.items()}


def get(url, tries=5):
    for a in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=150).read().decode()
        except Exception:
            time.sleep(8 * (a + 1))
    return None


def era5(lat, lon, year):
    key = "%s,%s,%d" % (lat, lon, year)
    if key in snocache:
        return snocache[key]
    if key in amcache:
        return amcache[key]
    q = {"latitude": lat, "longitude": lon, "start_date": "%d-01-01" % year, "end_date": "%d-12-31" % year,
         "hourly": "soil_temperature_0_to_7cm,soil_temperature_7_to_28cm", "temperature_unit": "fahrenheit", "timezone": "America/Los_Angeles"}
    t = get("https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(q))
    if not t:
        return None
    d = json.loads(t)
    out = {}
    for var, nm in (("soil_temperature_0_to_7cm", "s"), ("soil_temperature_7_to_28cm", "m")):
        by = defaultdict(list)
        for ts, v in zip(d["hourly"]["time"], d["hourly"][var]):
            if v is not None:
                by[ts[:10]].append(v)
        out[nm] = {k: sum(v) / len(v) for k, v in by.items() if len(v) >= 20}
    amcache[key] = out
    json.dump(amcache, open(AMC, "w"))
    return out


def model_weekly(lat, lon):
    s, m = {}, {}
    for y in YEARS:
        e = era5(lat, lon, y)
        if not e:
            return None
        s.update(e["s"]); m.update(e["m"])
        time.sleep(1)
    return {"a": weekly(s), "b": weekly(m)}


stations = []
# SNOTEL (forest clearings): start-of-day readings, depth a = 4 in, b = 8 in
for trip, s in sorted(sto.items(), key=lambda kv: kv[1]["elev"]):
    da, db = {}, {}
    for r in s["rows"]:
        if len(r) < 3 or r[0][:4] not in [str(y) for y in YEARS]:
            continue
        for tgt, val in ((da, r[1]), (db, r[2])):
            try:
                tgt[r[0]] = float(val) if val != "" else None
            except ValueError:
                pass
    if sum(1 for v in da.values() if v is not None) < 100:
        continue
    mdl = None
    if "%s,%s,2022" % (s["lat"], s["lon"]) in snocache and s["lon"] <= -121.0:
        mdl = model_weekly(s["lat"], s["lon"])
    stations.append({"id": trip, "name": s["name"], "net": "SNOTEL", "kind": "Forest clearing", "elev_ft": s["elev"], "lat": s["lat"], "lon": s["lon"],
                     "depth_a": "%d in" % abs(s["d4"]), "depth_b": "%d in" % abs(s["d8"]),
                     "sensor": {"a": weekly(da), "b": weekly(db)}, "model": mdl})
    print("SNOTEL", s["name"], "model" if mdl else "no model", flush=True)

# AgriMet (valley and coast fields)
AM = [("crvo", "Corvallis", "Willamette Valley", 44.63416, -123.19, 70, 4, 8), ("arao", "Aurora", "Willamette Valley", 45.28194, -122.75027, 42, None, 8),
      ("bano", "Bandon", "Coast", 43.09111, -124.41722, 24, 4, None), ("brko", "Brookings", "South coast", 42.03, -124.24083, 24, 6, 12),
      ("mdfo", "Medford", "Rogue Valley", 42.33111, -122.93777, 408, 4, None), ("kflo", "Klamath Falls", "East of the Cascades", 42.16472, -121.755, 1249, 4, 8),
      ("bato", "Beatty", "East of the Cascades", 42.47805, -121.27388, 1316, 4, 8)]
for sid, name, region, lat, lon, elev, d1, d2 in AM:
    sens = {}
    for tag, pc in (("a", "sw"), ("b", "sv")):
        if (tag == "a" and not d1) or (tag == "b" and not d2):
            continue
        daily = {}
        for y in YEARS:
            t = get("https://www.usbr.gov/pn-bin/instant.pl?station=%s&format=csv&year=%d&month=1&day=1&year=%d&month=12&day=31&pcode=%s" % (sid, y, y, pc))
            by = defaultdict(list)
            for row in csv.reader(io.StringIO(t or "")):
                if len(row) > 1 and row[0][:2] == "20" and row[1] != "":
                    try:
                        by[row[0][:10]].append(float(row[1]))
                    except ValueError:
                        pass
            daily.update({d: sum(v) / len(v) for d, v in by.items() if len(v) >= 80})
        sens[tag] = weekly(daily)
    mdl = model_weekly(lat, lon)
    stations.append({"id": sid, "name": name, "net": "AgriMet", "kind": region + " field", "elev_ft": elev, "lat": lat, "lon": lon,
                     "depth_a": ("%d in" % d1) if d1 else None, "depth_b": ("%d in" % d2) if d2 else None,
                     "sensor": {"a": sens.get("a"), "b": sens.get("b")}, "model": mdl})
    print("AgriMet", name, "model" if mdl else "no model", flush=True)

json.dump({"generated": "2026-11-09", "years": YEARS,
           "windows": {"morel": [41, 48, 56, 63], "chanterelle": [40, 45, 58, 65], "king_spring": [44, 50, 60, 66], "king_fall": [42, 45, 58, 64]},
           "note": "Weekly means of measured soil temperature (SNOTEL values are midnight readings) and the model's matching layers; deg F.",
           "stations": stations}, open(OUT, "w"), separators=(",", ":"))
print("stations", len(stations), "bytes", os.path.getsize(OUT))
