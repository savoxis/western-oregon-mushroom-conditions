"""Do valley-floor morel finds (Willamette Valley and Portland area, below 1,000 ft) line up with measured soil temperature?
Uses AgriMet (Bureau of Reclamation, public domain) 4/8-inch soil temperature at Corvallis (crvo, SW 4 in) and Aurora (arao, SV 8 in), and the public finds.
Aggregate output only. usage: python valley_morel.py sightings.json morel_elev.json out.json"""
import csv, io, json, math, statistics, sys, time, urllib.request
from collections import defaultdict
from datetime import date, timedelta

sj = json.load(open(sys.argv[1])); el = json.load(open(sys.argv[2]))
YEARS = list(range(2016, 2026))
ST = {"crvo": ("sw", 44.63416, -123.19), "arao": ("sv", 45.28194, -122.75027)}
UA = {"User-Agent": "shrooms-validation/1.0"}


def hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def daily(sid, pcode, y):
    url = "https://www.usbr.gov/pn-bin/instant.pl?station=%s&format=csv&year=%d&month=1&day=1&year=%d&month=12&day=31&pcode=%s" % (sid, y, y, pcode)
    for a in range(4):
        try:
            t = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read().decode()
            break
        except Exception:
            time.sleep(5 * (a + 1)); t = ""
    by = defaultdict(list)
    for row in csv.reader(io.StringIO(t)):
        if len(row) > 1 and row[0][:2] == "20" and row[1] != "":
            try: by[row[0][:10]].append(float(row[1]))
            except ValueError: pass
    return {d: sum(v) / len(v) for d, v in by.items() if len(v) >= 80}


import os
if os.path.exists("am_soil.json"):
    soil = json.load(open("am_soil.json"))
else:
    soil = {}
    for sid, (pc, la, lo) in ST.items():
        s = {}
        for y in YEARS:
            s.update(daily(sid, pc, y))
        soil[sid] = s
        print(sid, "days with soil data", len(s), "years", sorted({d[:4] for d in s}), flush=True)
    json.dump(soil, open("am_soil.json", "w"))


def mean7(s, d):
    base = date.fromisoformat(d)
    v = [s.get((base - timedelta(days=k)).isoformat()) for k in range(7)]
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if len(v) >= 5 else None


# valley finds: west of the crest, below 1,000 ft, 2016-2025, within 60 km of a station; unique days per station
finds = defaultdict(set)
for r in sj["rows"]:
    if r[1] != 1 or not ("2016" <= r[2][:4] <= "2025"):
        continue
    e = el.get("%s,%s" % (r[3], r[4]))
    if e is None or e >= 1000 or r[4] > -122.3:
        continue
    best = min(((hav(r[3], r[4], v[1], v[2]), k) for k, v in ST.items()))
    if best[0] <= 60:
        finds[best[1]].add(r[2])
report = {}
for sid, days in finds.items():
    s = soil[sid]
    vals = [(d, mean7(s, d)) for d in sorted(days)]
    vals = [(d, v) for d, v in vals if v is not None]
    if not vals:
        continue
    t = sorted(v for _, v in vals)
    # calendar baseline: all days Mar 1 - Jun 15 in the same years
    base = [mean7(s, d) for d in s if "03-01" <= d[5:] <= "06-15" and int(d[:4]) in YEARS]
    base = sorted(b for b in base if b is not None)
    pct = [100.0 * sum(1 for b in base if b < v) / len(base) for _, v in vals]
    # onset per year: first find date vs first date the 7-day soil mean reaches thresholds
    byyear = defaultdict(list)
    for d, _ in vals:
        byyear[d[:4]].append(d)
    onset = {}
    for y, ds in byyear.items():
        if len(ds) >= 3:
            ds = sorted(ds)
            onset[y] = ds[len(ds) // 4]               # first quartile find date = "season is on"
    corr = {}
    for T in (44, 46, 48, 50, 52, 54):
        xs, ys = [], []
        for y, fd in onset.items():
            cross = None
            d0 = date(int(y), 2, 1)
            for k in range(0, 140):
                dd = (d0 + timedelta(days=k)).isoformat()
                m = mean7(s, dd)
                if m is not None and m >= T:
                    cross = (d0 + timedelta(days=k)).timetuple().tm_yday; break
            if cross:
                xs.append(cross); ys.append(date.fromisoformat(fd).timetuple().tm_yday)
        if len(xs) >= 5:
            mx, my = statistics.mean(xs), statistics.mean(ys)
            den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
            lags = [b - a for a, b in zip(xs, ys)]
            corr[str(T)] = {"years": len(xs), "r": round(sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / den, 2) if den else None,
                            "median_lag_days": statistics.median(lags), "lag_sd_days": round(statistics.pstdev(lags), 1)}
    report[sid] = {"find_days": len(vals), "soil_7d_mean_on_find_days_F": {"p10": round(t[len(t) // 10], 1), "median": round(statistics.median(t), 1), "p90": round(t[(9 * len(t)) // 10], 1)},
                   "mean_percentile_vs_Mar1_Jun15_days": round(statistics.mean(pct), 1), "years_with_3plus_finds": sorted(onset), "onset_vs_threshold": corr}
json.dump(report, open(sys.argv[3], "w"), indent=1)
print(json.dumps(report, indent=1))
