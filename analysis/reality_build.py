"""Builds data/c/reality.json for the Stats tab ("scores against real reports"): static, aggregate-only numbers from the validation work.
usage: python reality_build.py sightings.json morel_elev.json val2_final_40.json val2_final_70.json sno_out.json am_out.json sno_forecast_out.json out.json"""
import json, sys, time, urllib.request, os
from collections import Counter

sj = json.load(open(sys.argv[1]))
el = json.load(open(sys.argv[2]))
v40, v70 = json.load(open(sys.argv[3])), json.load(open(sys.argv[4]))
sno, am = json.load(open(sys.argv[5])), json.load(open(sys.argv[6]))
fc = json.load(open(sys.argv[7]))
OUT = sys.argv[8]

# elevations (feet) for every find location: reuse the morel lookup, fetch the rest from the USGS 10 m model in batches of 100
EC = "all_elev.json"
elev = json.load(open(EC)) if os.path.exists(EC) else {}
for k, v in el.items():
    elev.setdefault(k, v)
pts = sorted({(r[3], r[4]) for r in sj["rows"]})
need = [p for p in pts if "%s,%s" % p not in elev]
for i in range(0, len(need), 100):
    chunk = need[i:i + 100]
    loc = "|".join("%s,%s" % p for p in chunk)
    d = None
    for a in range(5):
        try:
            d = json.load(urllib.request.urlopen("https://api.opentopodata.org/v1/ned10m?locations=" + loc, timeout=60))
            break
        except Exception:
            time.sleep(5 * (a + 1))
    for p, r in zip(chunk, (d or {}).get("results", [])):
        elev["%s,%s" % p] = None if r["elevation"] is None else r["elevation"] * 3.28084
    time.sleep(1.5)
json.dump(elev, open(EC, "w"))

BINS = list(range(0, 8500, 500))                       # 0-500 ... 8000+
fam = {"chanterelle": "chanterelle", "morel_natural": "morel", "king_spring": "king_spring", "king_fall": "king_fall"}
hist = {f: [0] * len(BINS) for f in fam.values()}
n_el = Counter()
for r in sj["rows"]:
    e = elev.get("%s,%s" % (r[3], r[4]))
    if e is None:
        continue
    f = fam[sj["species"][r[1]]]
    hist[f][min(int(e // 500), len(BINS) - 1)] += 1
    n_el[f] += 1

val = {}
for sp, o in v40["species"].items():
    o70 = v70["species"][sp]
    b, b70, c = o["B_effort_ge1"], o70["B_effort_ge1"], o.get("C_year_swap") or {}
    val[fam[sp]] = {"find_days": o["find_days"], "zones": o["zones_with_finds"], "lift60": o["A_lift_60"],
                    "rr": b["MH_risk_ratio"], "rr_ci": b["ci95"], "rr70": b70["MH_risk_ratio"], "rr70_ci": b70["ci95"],
                    "yswap": c.get("mean_percentile"), "yswap_ci": c.get("ci95")}

# soil: pooled SNOTEL bias by month (both layers) and station lists
tot = {"a": {}, "b": {}}
for s in sno["stations"].values():
    for lab, key in (("depth_a_vs_0_7cm_by_month", "a"), ("depth_b_vs_7_28cm_by_month", "b")):
        for mo, v in s.get(lab, {}).items():
            t = tot[key].setdefault(int(mo), [0, 0.0]); t[0] += v["n"]; t[1] += v["bias_f"] * v["n"]
soil = {"by_month_shallow": {m: round(t[1] / t[0], 1) for m, t in sorted(tot["a"].items())},
        "by_month_deep": {m: round(t[1] / t[0], 1) for m, t in sorted(tot["b"].items())},
        "snotel": sorted([{"name": s["name"], "elev_ft": s["elev_ft"], "bias_shallow": (s["depth_a_vs_0_7cm"] or {}).get("bias_f"),
                           "bias_deep": (s["depth_b_vs_7_28cm"] or {}).get("bias_f"), "corr": (s["depth_a_vs_0_7cm"] or {}).get("corr")}
                          for s in sno["stations"].values()], key=lambda x: x["elev_ft"]),
        "agrimet": [{"name": s["name"], "region": s["region"], "bias_shallow": (s.get("sw_vs_0_7cm") or {}).get("bias_f"),
                     "bias_deep": (s.get("sv_vs_7_28cm") or {}).get("bias_f"), "corr": (s.get("sw_vs_0_7cm") or s.get("sv_vs_7_28cm") or {}).get("corr")}
                    for s in am["stations"].values()],
        "live_model_bias_f": -1.4, "live_model_window": "Aug 8 to Nov 8 2026", "years": "2022-2025"}

out = {"generated": "2026-11-09",
       "find_elevation": {"bins_ft": BINS, "hist": hist, "n": dict(n_el)},
       "validation": val,
       "morel_band": {"share_in_band_all": 28, "share_in_band_public_land": 65, "share_below_1000ft": 57},
       "soil": soil}
json.dump(out, open(OUT, "w"), separators=(",", ":"))
print(json.dumps({"n_el": dict(n_el), "hist_morel": hist["morel"], "val": val, "soil_month": soil["by_month_shallow"]}, indent=1)[:2500])
