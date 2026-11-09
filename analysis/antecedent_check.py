"""Which stretches of past weather go with public finds? For every in-season zone-day on which other mushrooms were reported nearby
(people were out looking), compare how often the target mushroom was reported in the wettest / warmest third of days versus the driest /
coolest third, for several look-back windows. Thirds are cut within each zone, and the ratio is pooled across zones (Mantel-Haenszel),
so differences between zones do not count. Aggregate output only. Runs on the VPS (needs the weather database, no numpy):
    python3 antecedent_check.py /opt/shrooms/data/live_history.sqlite /opt/shrooms/data/series.json \
        /opt/shrooms/site/data/c/sightings.json agar_obs.json zones_all.json zones_extra.json out.json
"""
import json, math, sqlite3, sys
from collections import defaultdict
from datetime import date, timedelta

DB, SER, SJ, AG, ZA, ZX, OUT = sys.argv[1:8]
R = 40.0
YEARS = range(2016, 2026)
ser = json.load(open(SER))
sj = json.load(open(SJ))
ag = json.load(open(AG))["rows"]
zones = {z["id"]: z for z in json.load(open(ZA)) + json.load(open(ZX))["zones"]}
con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


def hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def nearest(lat, lon, ids):
    best = None
    for i in ids:
        z = zones[i]
        h = hav(lat, lon, z["lat"], z["lon"])
        if h <= R and (best is None or h < best[0]):
            best = (h, i)
    return best[1] if best else None


WIN = {"rain_7d": 7, "rain_14d": 14, "rain_30d": 30, "rain_60d": 60, "rain_90d": 90}
report = {"method": __doc__.strip().split("\n")[0], "species": {}}
for sp in sj["species"]:
    ids = sorted({k.split("|")[0] for k in ser if k.split("|")[1] == sp and k.split("|")[0] in zones})
    # weather per zone (ERA5 rows)
    wx = {}
    for z in ids:
        rows = con.execute("SELECT date, precip_in, temp_min_f, soil_t_shallow_f, soil_m_shallow FROM weather_daily WHERE zone=? AND source='era5' "
                           "AND date BETWEEN '2015-08-01' AND '2025-12-31'", (z,)).fetchall()
        wx[z] = {r[0]: r[1:] for r in rows}
    # target find-days and effort days
    tgt, eff = set(), defaultdict(int)
    si = sj["species"].index(sp)
    for r in sj["rows"]:
        if r[1] == si and 2016 <= int(r[2][:4]) <= 2025:
            z = nearest(r[3], r[4], ids)
            if z:
                tgt.add((z, r[2]))
    for d, la, lo, g in ag:
        if 2016 <= int(d[:4]) <= 2025:
            z = nearest(la, lo, ids)
            if z:
                eff[(z, d)] += 1
    # candidate days: scored (in season) and effort >= 1
    feats = defaultdict(list)       # name -> list of (zone, value, is_target)
    for z in ids:
        per = ser["%s|%s" % (z, sp)]
        W = wx[z]
        for y, arr in per.items():
            if int(y) not in YEARS:
                continue
            j1 = date(int(y), 1, 1)
            for i, sc in enumerate(arr):
                if sc is None:
                    continue
                d = j1 + timedelta(days=i)
                ds = d.isoformat()
                if eff.get((z, ds), 0) < 1:
                    continue
                past = [W.get((d - timedelta(days=k)).isoformat()) for k in range(91)]
                if sum(1 for p in past if p) < 80:
                    continue
                t = (z, ds) in tgt
                for name, n in WIN.items():
                    feats[name].append((z, sum((p[0] or 0) for p in past[:n] if p), t))
                feats["model_score"].append((z, sc, t))
                st = [p[2] for p in past[:7] if p and p[2] is not None]
                if st:
                    feats["soil_temp_7d"].append((z, sum(st) / len(st), t))
                frost = sum(1 for p in past[:14] if p and p[1] is not None and p[1] <= 28)
                feats["frost_nights_14d"].append((z, frost, t))
                sm = [p[3] for p in past[:7] if p and p[3] is not None]
                if sm:
                    feats["soil_moisture_7d"].append((z, sum(sm) / len(sm), t))
                if d.month >= 8:
                    since = [p for p in past[:(d - date(d.year, 8, 1)).days + 1] if p]
                    feats["rain_since_aug1"].append((z, sum((p[0] or 0) for p in since), t))
    res = {}
    for name, rows in feats.items():
        byz = defaultdict(list)
        for z, v, t in rows:
            byz[z].append((v, t))
        num = den = 0.0
        a1 = n1 = a0 = n0 = 0
        for z, lst in byz.items():
            if len(lst) < 30:
                continue
            vs = sorted(v for v, _ in lst)
            lo, hi = vs[len(vs) // 3], vs[(2 * len(vs)) // 3]
            if lo == hi:
                continue
            top = [t for v, t in lst if v > hi]
            bot = [t for v, t in lst if v <= lo]
            A, N1, C, N0 = sum(top), len(top), sum(bot), len(bot)
            Nn = N1 + N0
            if Nn:
                num += A * N0 / Nn
                den += C * N1 / Nn
            a1 += A; n1 += N1; a0 += C; n0 += N0
        res[name] = {"rr_top_vs_bottom_third": round(num / den, 2) if den else None, "finds_top": a1, "days_top": n1, "finds_bottom": a0, "days_bottom": n0}
    report["species"][sp] = {"find_days_in_test": sum(1 for z, v, t in feats["model_score"] if t), "effort_days": len(feats["model_score"]), "by_feature": res}
    print(sp, json.dumps(report["species"][sp]["find_days_in_test"]), {k: v["rr_top_vs_bottom_third"] for k, v in res.items()}, flush=True)
json.dump(report, open(OUT, "w"), indent=1)
