"""Compare measured soil temperature at AgriMet stations (Bureau of Reclamation, public domain) with the weather model values the site uses
(ERA5-Land layers via Open-Meteo). Aggregate output only.
usage: python am_validate.py out.json
AgriMet: https://www.usbr.gov/pn-bin/instant.pl (15-minute, SW = 4 in or 6 in, SV = 8 in or 12 in)."""
import csv, io, json, statistics, sys, time, urllib.parse, urllib.request
from collections import defaultdict

STATIONS = [  # id, name, lat, lon, region, sw column depth (in), sv column depth (in)
    ("crvo", "Corvallis (Willamette Valley)", 44.63416, -123.19, "valley", 4, 8),
    ("arao", "Aurora (Willamette Valley)", 45.28194, -122.75027, "valley", None, 8),
    ("bano", "Bandon (coast)", 43.09111, -124.41722, "coast", 4, None),
    ("brko", "Brookings (south coast)", 42.03, -124.24083, "coast", 6, 12),
    ("mdfo", "Medford (Rogue Valley)", 42.33111, -122.93777, "south", 4, None),
    ("kflo", "Klamath Falls (east)", 42.16472, -121.755, "east", 4, 8),
    ("bato", "Beatty (east)", 42.47805, -121.27388, "east", 4, 8),
]
YEARS = [2022, 2023, 2024, 2025]
UA = {"User-Agent": "shrooms-validation/1.0"}


def get(url, tries=5):
    for a in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read().decode()
        except Exception as e:
            err = e
            time.sleep(8 * (a + 1))
    print("FAILED", url[:90], err)
    return None


def agrimet_daily(sid, pcode, year):
    url = ("https://www.usbr.gov/pn-bin/instant.pl?station=%s&format=csv&year=%d&month=1&day=1&year=%d&month=12&day=31&pcode=%s" % (sid, year, year, pcode))
    t = get(url)
    if not t:
        return {}
    by = defaultdict(list)
    for row in csv.reader(io.StringIO(t)):
        if len(row) < 2 or not row[0][:2] == "20" or row[1] == "":
            continue
        try:
            by[row[0][:10]].append(float(row[1]))
        except ValueError:
            pass
    return {d: sum(v) / len(v) for d, v in by.items() if len(v) >= 80}      # need most of the day's 96 readings


def era5_daily(lat, lon, year):
    q = {"latitude": lat, "longitude": lon, "start_date": "%d-01-01" % year, "end_date": "%d-12-31" % year,
         "hourly": "soil_temperature_0_to_7cm,soil_temperature_7_to_28cm", "temperature_unit": "fahrenheit", "timezone": "America/Los_Angeles"}
    t = get("https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(q))
    if not t:
        return {}, {}
    d = json.loads(t)
    out = {}
    for var in ("soil_temperature_0_to_7cm", "soil_temperature_7_to_28cm"):
        by = defaultdict(list)
        for ts, v in zip(d["hourly"]["time"], d["hourly"][var]):
            if v is not None:
                by[ts[:10]].append(v)
        out[var] = {k: sum(v) / len(v) for k, v in by.items() if len(v) >= 20}
    return out["soil_temperature_0_to_7cm"], out["soil_temperature_7_to_28cm"]


def stats(pairs):
    if len(pairs) < 30:
        return None
    d = [m - s for m, s in pairs]
    ms = [m for m, s in pairs]; ss = [s for m, s in pairs]
    mm, sm = statistics.mean(ms), statistics.mean(ss)
    cov = sum((m - mm) * (s - sm) for m, s in pairs)
    den = (sum((m - mm) ** 2 for m in ms) * sum((s - sm) ** 2 for s in ss)) ** 0.5
    return {"n": len(pairs), "bias_f": round(statistics.mean(d), 1), "mae_f": round(statistics.mean(abs(x) for x in d), 1),
            "rmse_f": round((sum(x * x for x in d) / len(d)) ** 0.5, 1), "corr": round(cov / den, 3) if den else None}


report = {"note": "model minus station, deg F; model = ERA5-Land via Open-Meteo archive; station = AgriMet 15-minute readings averaged by local day", "stations": {}}
for sid, name, lat, lon, reg, dsw, dsv in STATIONS:
    sw, sv, m0, m1 = {}, {}, {}, {}
    for y in YEARS:
        if dsw:
            sw.update(agrimet_daily(sid, "sw", y))
        if dsv:
            sv.update(agrimet_daily(sid, "sv", y))
        a, b = era5_daily(lat, lon, y)
        m0.update(a); m1.update(b)
        time.sleep(1)
    res = {"name": name, "region": reg, "sw_depth_in": dsw, "sv_depth_in": dsv, "days_sw": len(sw), "days_sv": len(sv)}
    for lab, st, mod in (("sw_vs_0_7cm", sw, m0), ("sv_vs_7_28cm", sv, m1)):
        pairs = [(mod[d], st[d]) for d in st if d in mod]
        res[lab] = stats(pairs)
        seas = {}
        for mo, lab2 in ((3, "Mar"), (4, "Apr"), (5, "May"), (6, "Jun"), (9, "Sep"), (10, "Oct"), (11, "Nov")):
            p = [(mod[d], st[d]) for d in st if d in mod and int(d[5:7]) == mo]
            seas[lab2] = stats(p) and {"bias_f": stats(p)["bias_f"], "n": stats(p)["n"]}
        res[lab + "_by_month"] = seas
        # does the model put a day in the same 5-degree class as the sensor (<41, 41-48, 48-56, 56-63, >63)? uses the species' soil-temp triangle edges
        def cls(x): return 0 if x < 41 else 1 if x < 48 else 2 if x < 56 else 3 if x < 63 else 4
        p = [(mod[d], st[d]) for d in st if d in mod and int(d[5:7]) in (3, 4, 5, 6, 9, 10, 11)]
        if len(p) > 30:
            res[lab + "_same_class_share"] = round(sum(1 for m, s in p if cls(m) == cls(s)) / len(p), 3)
    report["stations"][sid] = res
    print(sid, json.dumps({k: res[k] for k in ("sw_vs_0_7cm", "sv_vs_7_28cm")}), flush=True)
json.dump(report, open(sys.argv[1], "w"), indent=1)
