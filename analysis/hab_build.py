"""Builds data/c/habitat.json from hab_raw.json (LANDFIRE 2024 samples): per-zone forest structure within ~6 km (5x5 grid, 3 km apart) and,
for each mushroom, how the public finds near a zone compare with the surrounding land. Aggregate only; no individual find is published."""
import json, math, sys

H = json.load(open(sys.argv[1]))
P, G = H["points"], H["zone_grids"]
sj = json.load(open(sys.argv[2]))
zs = {z["id"]: z for z in json.load(open(sys.argv[3])) + json.load(open(sys.argv[4]))["zones"]}
OUT = sys.argv[5]


def hav(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def feat(k):
    p = P[k]
    def num(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return None
    s, h, c = num(p.get("SClass")), num(p.get("EVH")), num(p.get("EVC"))
    th = h - 100 if h and 101 <= h <= 199 else None
    tc = c - 100 if c and 101 <= c <= 199 else None
    return {"forest": tc is not None, "late": tc is not None and s == 5, "late_any": tc is not None and s in (4, 5), "tall": th is not None and th >= 30, "th": th}


zones = {}
for zid, keys in G.items():
    fs = [feat(k) for k in keys]
    n = len(fs)
    ths = sorted(f["th"] for f in fs if f["th"])
    zones[zid] = {"forest": round(100 * sum(f["forest"] for f in fs) / n), "late": round(100 * sum(f["late"] for f in fs) / n),
                  "tall": round(100 * sum(f["tall"] for f in fs) / n), "med_height_m": ths[len(ths) // 2] if ths else None}
# tiers by (late + tall)/2 across all zones: top third strong, bottom third weak
score = {z: (v["late"] + v["tall"]) / 2 for z, v in zones.items()}
srt = sorted(score.values())
lo, hi = srt[len(srt) // 3], srt[(2 * len(srt)) // 3]
for z, v in zones.items():
    v["tier"] = "strong" if score[z] >= hi and score[z] > 0 else "weak" if score[z] <= lo else "average"

species = {}
for si, sp in enumerate(sj["species"]):
    fin, bg, n, nb = {"forest": 0, "late": 0, "tall": 0}, {"forest": 0.0, "late": 0.0, "tall": 0.0}, 0, 0.0
    for r in sj["rows"]:
        if r[1] != si:
            continue
        near = min(zs, key=lambda z: hav(r[3], r[4], zs[z]["lat"], zs[z]["lon"]))
        if hav(r[3], r[4], zs[near]["lat"], zs[near]["lon"]) > 40 or near not in G:
            continue
        f = feat("%s,%s" % (round(r[3], 3), round(r[4], 3)))
        n += 1
        for k in fin:
            fin[k] += f[k]
        w = 1 / len(G[near])
        for gk in G[near]:
            fb = feat(gk)
            nb += w
            for k in bg:
                bg[k] += w * fb[k]
    species[sp] = {"n": n, "finds_pct": {k: round(100 * v / n) for k, v in fin.items()}, "background_pct": {k: round(100 * v / nb) for k, v in bg.items()}}

out = {"generated": "2026-11-08", "source": "LANDFIRE 2024 (USGS and U.S. Forest Service, public domain): succession class, vegetation height and cover, 30 m pixels",
       "method": "5 x 5 grid, 3 km apart, centered on each zone (about 4 miles each way). Late = succession class E (late-development, closed canopy). Tall = trees 30 m (100 ft) or more.",
       "zones": zones, "species": species}
json.dump(out, open(OUT, "w"), separators=(",", ":"))
print(json.dumps(species, indent=1))
print(sorted(((v["late"], v["tall"], v["forest"], z) for z, v in zones.items()), reverse=True)[:6])
print(sum(1 for v in zones.values() if v["tier"] == "strong"), sum(1 for v in zones.values() if v["tier"] == "weak"), len(zones))
