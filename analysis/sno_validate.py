"""Model soil temperature (ERA5-Land layers via Open-Meteo, the history the site scores) vs measured soil temperature at NRCS SNOTEL stations
in forest clearings (public domain). Aggregate output only. usage: python sno_validate.py sto_data.json out.json
SNOTEL STO values are start-of-day (midnight) readings; the model values are local-day means."""
import json, os, statistics, sys, time, urllib.parse, urllib.request
from collections import defaultdict

data = json.load(open(sys.argv[1]))
OUT = sys.argv[2]
YEARS = [2022, 2023, 2024, 2025]
CACHE = "sno_era5_cache.json"
cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
UA = {"User-Agent": "shrooms-validation/1.0"}


def era5(lat, lon, year):
    key = "%s,%s,%d" % (lat, lon, year)
    if key in cache:
        return cache[key]
    q = {"latitude": lat, "longitude": lon, "start_date": "%d-01-01" % year, "end_date": "%d-12-31" % year,
         "hourly": "soil_temperature_0_to_7cm,soil_temperature_7_to_28cm", "temperature_unit": "fahrenheit", "timezone": "America/Los_Angeles"}
    for a in range(6):
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request("https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(q), headers=UA), timeout=120).read().decode())
            break
        except Exception as e:
            d = None
            time.sleep(10 * (a + 1))
    if not d:
        return None
    out = {}
    for var, nm in (("soil_temperature_0_to_7cm", "s"), ("soil_temperature_7_to_28cm", "m")):
        by = defaultdict(list)
        for ts, v in zip(d["hourly"]["time"], d["hourly"][var]):
            if v is not None:
                by[ts[:10]].append(v)
        out[nm] = {k: sum(v) / len(v) for k, v in by.items() if len(v) >= 20}
    out["elev"] = d.get("elevation")
    cache[key] = out
    json.dump(cache, open(CACHE, "w"))
    return out


def stats(pairs):
    if len(pairs) < 40:
        return None
    ms = [m for m, s in pairs]; ss = [s for m, s in pairs]
    d = [m - s for m, s in pairs]
    mm, sm = statistics.mean(ms), statistics.mean(ss)
    den = (sum((m - mm) ** 2 for m in ms) * sum((s - sm) ** 2 for s in ss)) ** 0.5
    return {"n": len(pairs), "bias_f": round(statistics.mean(d), 1), "mae_f": round(statistics.mean(abs(x) for x in d), 1),
            "corr": round(sum((m - mm) * (s - sm) for m, s in pairs) / den, 3) if den else None}


report = {"note": "model minus SNOTEL, deg F; SNOTEL start-of-day readings vs ERA5-Land local-day means; snow-covered days (sensor under 36 F) excluded", "stations": {}}
allpairs = defaultdict(list)
for trip, s in data.items():
    n_ok = sum(1 for r in s["rows"] if len(r) > 2 and r[1] != "")
    if n_ok < 300 or s["lon"] < -122.4 and s["elev"] > 99999:
        continue
    if s["lon"] > -121.0:                          # keep west slope and crest stations plus the near-crest east side; skip the far east and northeast
        continue
    m = {}
    for y in YEARS:
        e = era5(s["lat"], s["lon"], y)
        if e:
            for k in ("s", "m"):
                m.setdefault(k, {}).update(e[k])
        time.sleep(1)
    res = {"name": s["name"], "elev_ft": s["elev"], "d_a": s["d4"], "d_b": s["d8"], "model_elev_m": None}
    pairs_a, pairs_b = [], []
    for r in s["rows"]:
        if len(r) < 3 or r[0][:4] not in [str(y) for y in YEARS]:
            continue
        d = r[0]
        try:
            a, b = (float(r[1]) if r[1] != "" else None), (float(r[2]) if r[2] != "" else None)
        except ValueError:
            continue
        if a is not None and a > 36 and d in m.get("s", {}):
            pairs_a.append((m["s"][d], a, int(d[5:7])))
        if b is not None and b > 36 and d in m.get("m", {}):
            pairs_b.append((m["m"][d], b, int(d[5:7])))
    for lab, pr in (("depth_a_vs_0_7cm", pairs_a), ("depth_b_vs_7_28cm", pairs_b)):
        res[lab] = stats([(x[0], x[1]) for x in pr])
        by = {}
        for mo in (4, 5, 6, 7, 8, 9, 10, 11):
            sub = [(x[0], x[1]) for x in pr if x[2] == mo]
            st = stats(sub)
            if st:
                by[mo] = {"bias_f": st["bias_f"], "n": st["n"]}
        res[lab + "_by_month"] = by
        for x in pr:
            allpairs[(lab, "<4000" if s["elev"] < 4000 else "4000-5600" if s["elev"] < 5600 else "5600+")].append((x[0], x[1]))
    report["stations"][trip] = res
    print(trip, s["name"], s["elev"], json.dumps({k: res[k] for k in ("depth_a_vs_0_7cm", "depth_b_vs_7_28cm")}), flush=True)
report["by_elevation_band"] = {"%s %s" % k: stats(v) for k, v in allpairs.items()}
json.dump(report, open(OUT, "w"), indent=1)
print(json.dumps(report["by_elevation_band"], indent=1))
