"""Effort-controlled validation of the site's scores against public finds. Aggregate output only.
usage: python val2.py series.json zones_all.json zones_extra.json sightings.json agar_obs.json out.json [radius_km]
Tests (unique zone-days, 2016-2025 scored in-season days):
  A  baseline lift: share of find-days on 60+ days vs share of all in-season days on 60+
  B  effort-controlled: among days when someone reported OTHER mushrooms nearby (effort >= 1 or >= 3), how much more often is the target
     also reported on 60+ days than on <40 days? Mantel-Haenszel risk ratio across zones, zone-year cluster bootstrap CI.
  C  year-swap: score on the find day vs the score on the same calendar window (+-3 d) in other years of the same zone;
     50 = the score adds nothing beyond the calendar.
"""
import json, math, sys, bisect
from datetime import date, timedelta
import numpy as np

series = json.load(open(sys.argv[1]))
zones = {z["id"]: z for z in json.load(open(sys.argv[2])) + json.load(open(sys.argv[3]))["zones"]}
sj = json.load(open(sys.argv[4]))
agar = json.load(open(sys.argv[5]))["rows"]
OUT = sys.argv[6]
R = float(sys.argv[7]) if len(sys.argv) > 7 else 40.0
YEARS = list(range(2016, 2026))                     # complete ERA5 years (2026 is partial and mixes forecast data)
rng = np.random.default_rng(7)


def hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def doy(d):
    y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
    return y, (date(y, m, dd) - date(y, 1, 1)).days


def nearest(lat, lon, keys):
    best = None
    for k in keys:
        z = zones[k[0]]
        h = hav(lat, lon, z["lat"], z["lon"])
        if h <= R and (best is None or h < best[0]):
            best = (h, k)
    return best[1] if best else None


report = {"radius_km": R, "years": "%d-%d" % (YEARS[0], YEARS[-1]), "species": {}}
for sp in sj["species"]:
    keys = [tuple(k.split("|")) for k in series if k.split("|")[1] == sp]
    keys = [k for k in keys if k[0] in zones]
    skey = {k: "%s|%s" % k for k in keys}
    score = {}                                      # (zone, year, doy0) -> score, only scored days
    for k in keys:
        for y, arr in series[skey[k]].items():
            if int(y) not in YEARS:
                continue
            for i, v in enumerate(arr):
                if v is not None:
                    score[(k[0], int(y), i)] = v
    # target find-days
    tdays = set()
    for r in sj["rows"]:
        if sj["species"][r[1]] != sp:
            continue
        y, i = doy(r[2])
        if y not in YEARS:
            continue
        k = nearest(r[3], r[4], keys)
        if k and (k[0], y, i) in score:
            tdays.add((k[0], y, i))
    # effort days (other mushrooms), any date, assigned to nearest zone for this species
    eff = {}
    for d, la, lo, g in agar:
        y, i = doy(d)
        if y not in YEARS:
            continue
        k = nearest(la, lo, keys)
        if k and (k[0], y, i) in score:
            eff[(k[0], y, i)] = eff.get((k[0], y, i), 0) + 1
    zlist = sorted({k[0] for k in keys})
    zi = {z: j for j, z in enumerate(zlist)}
    days = list(score.keys())
    sc = np.array([score[d] for d in days])
    isT = np.array([d in tdays for d in days])
    E = np.array([eff.get(d, 0) for d in days])
    zidx = np.array([zi[d[0]] for d in days])
    cl = {}
    for j, d in enumerate(days):
        cl.setdefault((d[0], d[1]), []).append(j)
    cl_list = list(cl.values())

    out = {"find_days": int(isT.sum()), "scored_days": len(days), "zones_with_finds": len({d[0] for d in tdays})}
    # A
    hi = sc >= 60
    out["A_share_finddays_60plus"] = round(float(hi[isT].mean() * 100), 1) if isT.any() else None
    out["A_share_allseasondays_60plus"] = round(float(hi.mean() * 100), 1)
    out["A_lift_60"] = round(out["A_share_finddays_60plus"] / out["A_share_allseasondays_60plus"], 2) if isT.any() else None

    # B
    def mh(mask, idx_clusters):
        # Mantel-Haenszel RR (60+ vs <40) across zones; clusters = list of index arrays (zone-year)
        S = len(zlist)
        n1 = np.zeros(S); a1 = np.zeros(S); n0 = np.zeros(S); a0 = np.zeros(S)
        for idxs in idx_clusters:
            idxs = np.asarray(idxs)
            m = mask[idxs]
            ii = idxs[m]
            if not len(ii):
                continue
            z = zidx[ii]
            h = sc[ii] >= 60
            l = sc[ii] < 40
            np.add.at(n1, z[h], 1); np.add.at(a1, z[h], isT[ii][h])
            np.add.at(n0, z[l], 1); np.add.at(a0, z[l], isT[ii][l])
        N = n1 + n0
        ok = N > 0
        num = (a1 * n0 / np.where(ok, N, 1))[ok].sum()
        den = (a0 * n1 / np.where(ok, N, 1))[ok].sum()
        return (num / den if den > 0 else float("nan")), n1.sum(), a1.sum(), n0.sum(), a0.sum()
    for lab, mask in (("all_days", np.ones(len(days), bool)), ("effort_ge1", E >= 1), ("effort_ge3", E >= 3)):
        rr, n1, a1, n0, a0 = mh(mask, cl_list)
        boots = []
        if a1 + a0 >= 5:
            for _ in range(600):
                pick = rng.integers(0, len(cl_list), len(cl_list))
                b = mh(mask, [cl_list[p] for p in pick])[0]
                if np.isfinite(b):
                    boots.append(b)
        ci = (round(float(np.percentile(boots, 2.5)), 2), round(float(np.percentile(boots, 97.5)), 2)) if len(boots) > 100 else None
        out["B_" + lab] = {"days_60plus": int(n1), "find_days_60plus": int(a1), "rate_60plus_pct": round(a1 / n1 * 100, 1) if n1 else None,
                          "days_lt40": int(n0), "find_days_lt40": int(a0), "rate_lt40_pct": round(a0 / n0 * 100, 1) if n0 else None,
                          "MH_risk_ratio": round(float(rr), 2) if np.isfinite(rr) else None, "ci95": ci}
    # C
    pcts = []
    zy = {}
    for (z, y, i) in tdays:
        others = []
        for yy in YEARS:
            if yy == y:
                continue
            for dd in range(i - 3, i + 4):
                v = score.get((z, yy, dd))
                if v is not None:
                    others.append(v)
        if len(others) < 10:
            continue
        s0 = score[(z, y, i)]
        lo_, hi_ = sum(1 for v in others if v < s0), sum(1 for v in others if v <= s0)
        pcts.append((lo_ + hi_) / 2 / len(others) * 100)
        zy.setdefault((z, y), []).append(pcts[-1])
    if pcts:
        cls = list(zy.values())
        bm = []
        for _ in range(1000):
            pick = rng.integers(0, len(cls), len(cls))
            bm.append(np.mean(np.concatenate([cls[p] for p in pick])))
        out["C_year_swap"] = {"n_days": len(pcts), "mean_percentile": round(float(np.mean(pcts)), 1),
                              "ci95": (round(float(np.percentile(bm, 2.5)), 1), round(float(np.percentile(bm, 97.5)), 1)),
                              "share_above_median": round(float(np.mean([p > 50 for p in pcts]) * 100), 1)}
    report["species"][sp] = out

json.dump(report, open(OUT, "w"), indent=1)
print(json.dumps(report, indent=1))
