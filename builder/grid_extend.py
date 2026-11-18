#!/usr/bin/env python3
"""grid_extend.py - adds heat-map sample points where the map has none yet (mainly east of the Cascades), only over forest.

The heat map is drawn from unlisted sample points in data/grid.json (ids start with g_). The list was made for western Oregon,
so the Ochocos, Blue Mountains, Wallowas and Malheur country have no colour. This script:
  1. reads the current points and measures their spacing (median distance to the nearest neighbour),
  2. lays a lattice at that spacing over Oregon and keeps the spots farther than 0.75 x spacing from every current point,
  3. keeps only spots with real forest around them: LANDFIRE 2024 tree cover (EVC 101-199) on a 5 x 5 grid, 3 km apart,
     must be at least --min-forest percent (default 30). Sagebrush, farmland and lava stay blank on the map, as they should,
  4. reads each kept spot's elevation (Open-Meteo elevation API, through om_key when a key is set) and drops spots at water
     level or outside every elevation band of their species (the model could never score them),
  5. copies side, coastal, species and any other fields from the nearest current point on the same side of the Cascades.
Free data only. The new points are scored by the same model; the hourly fill backfills them like any grid point.

usage, as the build user on the VPS:
  cd /opt/shrooms && python3 -B grid_extend.py              dry run: the new points, their forest share and the backfill cost
  cd /opt/shrooms && python3 -B grid_extend.py --write      backs up data/grid.json, then appends the new points
options:
  --min-forest PCT   forest share a spot needs (default 30)
  --spacing KM       lattice spacing (default: measured from the current points)
  --skip ID,ID       leave out these point ids (as the dry run prints them)
  --force            write even while listed zones are still backfilling (normally refused, so zones fill first)
Rollback: copy the data/grid.json.bak-* file this prints back over data/grid.json. Stdlib only."""
import json, math, os, sys, time, urllib.parse, urllib.request
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import burns_2027 as B  # noqa: E402  (Oregon outline and point-in-polygon)

ROOT = os.environ.get("SHROOMS_ROOT", "/opt/shrooms")
SKILL = os.environ.get("SHROOMS_SKILL", "/opt/mushroom-scout")
GRID = os.path.join(ROOT, "data", "grid.json")
CACHE = os.path.join(ROOT, "cache")
LF = "https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2024/LF2024_EVC_CONUS/ImageServer/getSamples"
ELEV = "https://api.open-meteo.com/v1/elevation"
UA = {"User-Agent": "shrooms-tracker (grid extend)"}
FIRST_YEAR = 2016
LITE_COST = 26                     # weighted free-archive calls per lite file (same as run_fill)
DAILY_CAP = 4500                   # what the backfill may spend a day (same as run_fill)
# Cascade crest, south to north (lat, lon). Spots this far east of it are "east" side; others copy the nearest point's side.
CREST = [(41.9, -122.25), (42.5, -122.25), (43.0, -122.15), (43.5, -122.05), (44.0, -121.85), (44.5, -121.85),
         (45.0, -121.75), (45.4, -121.75), (45.7, -121.85), (46.3, -121.9)]
EAST_MARGIN = 0.3                  # degrees of longitude east of the crest


def load(path):
    with open(path) as fh:
        return json.load(fh)


def hav(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def crest_lon(lat):
    if lat <= CREST[0][0]:
        return CREST[0][1]
    for (a, x), (b, y) in zip(CREST, CREST[1:]):
        if a <= lat <= b:
            return x + (y - x) * (lat - a) / (b - a)
    return CREST[-1][1]


def is_east(lat, lon):
    return lon >= crest_lon(lat) + EAST_MARGIN


def spacing_km(points):
    d = sorted(min(hav(p["lat"], p["lon"], q["lat"], q["lon"]) for q in points if q is not p) for p in points)
    return d[len(d) // 2]


def lattice(oregon, anchor, km):
    """Every lattice spot inside Oregon, aligned to one current point so new spots line up with the old ones."""
    dlat = km / 111.2
    dlon = km / (111.32 * math.cos(math.radians(44.0)))
    xs = [x for poly in oregon for x, _ in poly[0]]
    ys = [y for poly in oregon for _, y in poly[0]]
    i0, i1 = math.floor((min(ys) - anchor["lat"]) / dlat), math.ceil((max(ys) - anchor["lat"]) / dlat)
    j0, j1 = math.floor((min(xs) - anchor["lon"]) / dlon), math.ceil((max(xs) - anchor["lon"]) / dlon)
    out = []
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            la, lo = round(anchor["lat"] + i * dlat, 3), round(anchor["lon"] + j * dlon, 3)
            if B.in_polys(lo, la, oregon):
                out.append((la, lo))
    return out


def ring25(lat, lon):
    """5 x 5 sample spots 3 km apart (about 6 km each way), as in analysis/hab_fetch.py."""
    k = 3 / (111.2 * math.cos(math.radians(lat)))
    return [(round(lat + i * 3 / 111.2, 4), round(lon + j * k, 4)) for i in range(-2, 3) for j in range(-2, 3)]


def _post(url, data, timeout=120, tries=4):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as exc:
            err = exc
            time.sleep(4 * (a + 1))
    raise RuntimeError("LANDFIRE request failed: %r" % err)


def landfire_evc(spots):
    """LANDFIRE 2024 existing vegetation cover at each (lat, lon); 101-199 means tree cover. None where it gave no answer."""
    out = []
    for s in range(0, len(spots), 400):
        chunk = spots[s:s + 400]
        d = _post(LF, {"geometry": json.dumps({"points": [[lo, la] for la, lo in chunk], "spatialReference": {"wkid": 4326}}),
                       "geometryType": "esriGeometryMultipoint", "returnFirstValueOnly": "true", "f": "json"})
        vals = {r["locationId"]: r.get("value") for r in d.get("samples", [])}
        for i in range(len(chunk)):
            try:
                out.append(int(vals.get(i)))
            except (TypeError, ValueError):
                out.append(None)
        time.sleep(0.3)
    return out


def elevations_ft(spots):
    try:
        import om_key
        opener = om_key.urlopen
    except ImportError:
        opener = urllib.request.urlopen
    out = []
    for s in range(0, len(spots), 100):
        chunk = spots[s:s + 100]
        url = ELEV + "?" + urllib.parse.urlencode({"latitude": ",".join(str(a) for a, _ in chunk),
                                                   "longitude": ",".join(str(b) for _, b in chunk)})
        with opener(urllib.request.Request(url, headers=UA), timeout=60) as r:
            d = json.loads(r.read().decode())
        out += [int(round(m * 3.28084 / 10.0)) * 10 for m in d["elevation"]]
        time.sleep(0.3)
    return out


def forest_share(evc, n_spots):
    """Percent of each spot's 25 samples that are tree cover; None when LANDFIRE answered for fewer than half of them."""
    out = []
    for i in range(n_spots):
        vals = evc[i * 25:(i + 1) * 25]
        known = [v for v in vals if v is not None]
        out.append(None if len(known) < 13 else round(100 * sum(1 for v in known if 101 <= v <= 199) / len(known)))
    return out


def template_for(lat, lon, points):
    east = is_east(lat, lon)
    same = [p for p in points if (p.get("side") == "east") == east] if east else points
    pool = same or points
    return min(pool, key=lambda p: hav(lat, lon, p["lat"], p["lon"])), east


def new_point(lat, lon, elev, points):
    t, east = template_for(lat, lon, points)
    p = json.loads(json.dumps(t))
    for k in ("live", "name"):
        p.pop(k, None)
    p.update({"id": "g_x%04d_%05d" % (round(lat * 100), round(-lon * 100)), "lat": lat, "lon": lon, "elev_ft": elev})
    if east:
        p["side"] = "east"
        p["coastal"] = False
        if t.get("side") != "east":
            p["species"] = ["morel_natural", "king_spring"]
    return p


def load_bands():
    """Elevation bands per species from the skill's registry, or {} when it is not found (then no band check)."""
    for path in (os.path.join(SKILL, "references", "species_registry.json"),
                 os.path.join(HERE, "..", "scout", "references", "species_registry.json")):
        try:
            return {k: v.get("elev_bands_ft") for k, v in load(path)["species"].items()}
        except (OSError, ValueError, KeyError):
            continue
    return {}


def scorable(p, bands):
    """True when the point's elevation sits inside at least one band of one of its species, so the model can ever score it."""
    known = [bands[k] for k in p.get("species", []) if bands.get(k)]
    if not known:
        return True
    return any(lo <= p["elev_ft"] <= hi for b in known for lo, hi in b.values())


def plan(points, oregon, km, min_forest, evc_fn=landfire_evc, elev_fn=elevations_ft, bands=None, skip=()):
    """Returns (new points, rejected spots with reasons). Network goes only through evc_fn and elev_fn.
    Also dropped: spots at water level (10 ft or less), spots above or below every band of their species, and ids in skip."""
    bands = load_bands() if bands is None else bands
    cands = [(la, lo) for la, lo in lattice(oregon, points[0], km)
             if min(hav(la, lo, p["lat"], p["lon"]) for p in points) > 0.75 * km]
    rings = [s for la, lo in cands for s in ring25(la, lo)]
    share = forest_share(evc_fn(rings) if rings else [], len(cands))
    keep, rejected = [], []
    for (la, lo), f in zip(cands, share):
        if f is None:
            rejected.append((la, lo, "no LANDFIRE answer"))
        elif f < min_forest:
            rejected.append((la, lo, "%d%% forest" % f))
        else:
            keep.append((la, lo, f))
    elevs = elev_fn([(la, lo) for la, lo, _ in keep]) if keep else []
    new = []
    for (la, lo, f), e in zip(keep, elevs):
        p = new_point(la, lo, e, points)
        p["_forest_pct"] = f
        if p["id"] in skip:
            rejected.append((la, lo, "skipped by hand"))
        elif e <= 10:
            rejected.append((la, lo, "at water level"))
        elif not scorable(p, bands):
            rejected.append((la, lo, "%d ft is outside every species band" % e))
        else:
            new.append(p)
    return new, rejected


def zones_still_filling(years):
    """Listed zones that are missing archive files for some year: the grid waits for them (they matter more)."""
    ids = []
    for path in (os.path.join(SKILL, "references", "zones.json"), os.path.join(ROOT, "zones_extra.json")):
        try:
            ids += [z["id"] for z in load(path)["zones"]]
        except (OSError, ValueError, KeyError):
            pass
    miss = []
    for zid in ids:
        if any(not (os.path.exists("%s/arch2_%s_%d.json" % (CACHE, zid, y)) or os.path.exists("%s/arch_%s_%d.json" % (CACHE, zid, y)))
               for y in years):
            miss.append(zid)
    return miss


def write_grid(doc, new, path=GRID):
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    bak = "%s.bak-%s" % (path, stamp)
    with open(path) as src, open(bak, "w") as dst:
        dst.write(src.read())
    doc = dict(doc)
    doc["points"] = list(doc["points"]) + [{k: v for k, v in p.items() if not k.startswith("_")} for p in new]
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    os.replace(tmp, path)
    return bak


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    write, force = "--write" in argv, "--force" in argv
    min_forest = int(argv[argv.index("--min-forest") + 1]) if "--min-forest" in argv else 30
    skip = set(argv[argv.index("--skip") + 1].split(",")) if "--skip" in argv else set()
    doc = load(GRID)
    points = doc["points"]
    if len(points) < 3:
        print("data/grid.json has fewer than 3 points; nothing to measure the spacing from")
        return 1
    km = float(argv[argv.index("--spacing") + 1]) if "--spacing" in argv else spacing_km(points)
    oregon = B.load_oregon(next((p for p in (os.path.join(ROOT, "site", "oregon.json"), os.path.join(HERE, "..", "site", "oregon.json"))
                                 if os.path.exists(p)), ""))
    if not oregon:
        print("oregon.json not found next to the site")
        return 1
    ids = {p["id"] for p in points}
    print("current grid: %d points, spacing %.1f km" % (len(points), km))
    new, rejected = plan(points, oregon, km, min_forest, skip=skip)
    new = [p for p in new if p["id"] not in ids]
    years = list(range(FIRST_YEAR, date.today().year + 1))
    calls = len(new) * len(years) * LITE_COST
    print("%d new forest points (min %d%% forest); %d spots left blank" % (len(new), min_forest, len(rejected)))
    for la, lo, why in rejected:
        if "forest" not in why and "LANDFIRE" not in why:
            print("  dropped %.3f,%.3f: %s" % (la, lo, why))
    print("%-18s %8s %9s %7s %-6s %s" % ("id", "lat", "lon", "elev_ft", "side", "forest"))
    for p in sorted(new, key=lambda p: (-p["lat"], p["lon"])):
        print("%-18s %8.3f %9.3f %7d %-6s %d%%" % (p["id"], p["lat"], p["lon"], p["elev_ft"], p.get("side"), p["_forest_pct"]))
    print("backfill: about %d weighted free-archive calls (%d years), roughly %d days at %d a day; live scoring costs nothing "
          "extra off-season" % (calls, len(years), math.ceil(calls / DAILY_CAP) if calls else 0, DAILY_CAP))
    if not write:
        print("dry run: nothing written. Add --write to append these points.")
        return 0
    filling = zones_still_filling(years)
    if filling and not force:
        print("not written: %d listed zones are still backfilling (%s). Run again once they finish, or add --force."
              % (len(filling), ", ".join(filling[:6]) + (" ..." if len(filling) > 6 else "")))
        return 2
    if not new:
        print("nothing to write")
        return 0
    bak = write_grid(doc, new)
    print("wrote %d points to %s; backup at %s" % (len(new), GRID, bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
