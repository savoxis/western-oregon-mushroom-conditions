#!/usr/bin/env python3
"""burns_2027.py - free teaser layer for the 2027 Burn Morel Pass.

Pulls every Oregon wildfire perimeter from a given fire year (default 2026) at or over
--min-acres from NIFC WFIGS, drops the fires on the exclusion list (tribal land and anything
else we will not send people to), joins a hand-kept closure table and an optional conifer-acre
table, simplifies the outlines and writes site/data/c/burns.json for the map's "2026 burns" layer.

Statewide on purpose: the biggest conifer burns of 2026 (Ochoco, Umatilla, Blue Mountains) sit
east of the scoring zones and outside scout/scripts/fires.py's western bounding box.

Stdlib only. Run on the VPS as user mushroom, weekly from November through June:
    python3 -B /opt/shrooms/burns_2027.py                      (live query, writes the site file)
    python3 -B burns_2027.py --fixture f.geojson --out x.json  (offline, for tests)
    python3 -B burns_2027.py --dry-run                         (prints a summary, writes nothing)

Inputs kept by hand next to this script (burn_pass/):
    closures.json   {"Fire Name": {"status": "open|partial|closed|unknown", "order_url": "https://...",
                                   "checked": "YYYY-MM-DD", "note": "..."}}
    exclude.json    [{"name": "Fire Name", "reason": "..."}]
    conifer.csv     optional; header row with a name column and a column whose header contains
                    "conifer" (acres). Matched on fire name, case-insensitive.
"""
import argparse, csv, datetime, json, math, os, sys, tempfile, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("SHROOMS_ROOT", "/opt/shrooms")
SITE_DATA = os.environ.get("SHROOMS_SITE_DATA", ROOT + "/site/data")
PASS_DIR = os.environ.get("BURN_PASS_DIR", os.path.join(HERE, "burn_pass"))
UA = {"User-Agent": "shrooms-tracker (static site generator)"}
WFIGS = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
         "WFIGS_Interagency_Perimeters/FeatureServer/0/query")
# Oregon, generous on every side; the state filter does the real work
OR_BBOX = (-124.8, 41.9, -116.4, 46.35)
STATUS = ("open", "partial", "closed", "unknown")


# ---------------------------------------------------------------- fetch
def query_wfigs(year, min_acres, state="US-OR", page=500, tries=3):
    """All Oregon perimeters for one fire year, as GeoJSON features. Pages until the server stops.
    state="" drops the point-of-origin filter and leans on the bounding box alone (picks up some
    Washington, Idaho, California and Nevada edges; use it only if the state filter returns nothing)."""
    where = ("poly_GISAcres >= %d "
             "AND attr_FireDiscoveryDateTime >= DATE '%d-01-01' "
             "AND attr_FireDiscoveryDateTime < DATE '%d-01-01'") % (min_acres, year, year + 1)
    if state:
        where = "attr_POOState = '%s' AND " % state.replace("'", "") + where
    feats, offset = [], 0
    while True:
        q = {
            "where": where, "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "geojson",
            "geometry": ",".join(str(v) for v in OR_BBOX), "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
            "maxAllowableOffset": "0.0004", "geometryPrecision": "5",
            "resultOffset": str(offset), "resultRecordCount": str(page), "orderByFields": "poly_GISAcres DESC",
        }
        url = WFIGS + "?" + urllib.parse.urlencode(q)
        data = None
        for i in range(tries):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                    data = json.load(r)
                break
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                if i == tries - 1:
                    raise RuntimeError("WFIGS query failed: %s" % e)
                time.sleep(5 * (i + 1))
        if "error" in data:
            raise RuntimeError("WFIGS error: %s" % json.dumps(data["error"])[:300])
        got = data.get("features") or []
        feats.extend(got)
        more = data.get("exceededTransferLimit") or (data.get("properties") or {}).get("exceededTransferLimit")
        if not got or not more:
            return feats
        offset += len(got)


# ---------------------------------------------------------------- geometry
def _perp(p, a, b):
    """Distance from p to segment a-b in degrees, longitude scaled by cos(latitude)."""
    k = math.cos(math.radians(a[1]))
    px, py, ax, ay, bx, by = p[0] * k, p[1], a[0] * k, a[1], b[0] * k, b[1]
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplify(ring, tol):
    """Douglas-Peucker on one closed ring, iterative so long outlines cannot blow the stack."""
    if len(ring) < 5:
        return ring
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        s, e = stack.pop()
        best, idx = 0.0, -1
        for i in range(s + 1, e):
            d = _perp(ring[i], ring[s], ring[e])
            if d > best:
                best, idx = d, i
        if idx >= 0 and best > tol:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    out = [p for p, k in zip(ring, keep) if k]
    return out if len(out) >= 4 else []


def ring_acres(ring):
    """Rough planar area of a lon/lat ring in acres (fine for dropping slivers, not for reporting)."""
    if len(ring) < 4:
        return 0.0
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    kx, ky = 111320.0 * math.cos(lat0), 110540.0
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        a += (x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky)
    return abs(a) / 2 / 4046.86


def clean_polys(geom, tol, min_ring_acres):
    """GeoJSON Polygon or MultiPolygon -> list of polygons, each a list of rings of [lon, lat]."""
    if not geom:
        return []
    t = geom.get("type")
    polys = [geom["coordinates"]] if t == "Polygon" else geom.get("coordinates", []) if t == "MultiPolygon" else []
    out = []
    for poly in polys:
        rings = []
        for i, ring in enumerate(poly):
            pts = [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in ring if len(p) >= 2]
            dedup = [pts[0]] if pts else []
            for p in pts[1:]:
                if p != dedup[-1]:
                    dedup.append(p)
            if dedup and dedup[0] != dedup[-1]:
                dedup.append(dedup[0])
            r = simplify(dedup, tol)
            if not r or ring_acres(r) < min_ring_acres:
                if i == 0:
                    break          # outer ring gone, so the holes go too
                continue
            rings.append(r)
        if rings:
            out.append(rings)
    return out


# ---------------------------------------------------------------- side tables
def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def norm(name):
    s = (name or "").strip().lower()
    for suffix in (" fire", " complex"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return " ".join(s.split())


def load_conifer(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return {}
    head = [c.strip().lower() for c in rows[0]]
    ni = next((i for i, c in enumerate(head) if "name" in c or c == "fire"), None)
    ci = next((i for i, c in enumerate(head) if "conifer" in c and "pct" not in c and "%" not in c), None)
    if ni is None or ci is None:
        raise ValueError("conifer CSV needs a name column and a conifer-acres column, got %s" % rows[0])
    out = {}
    for r in rows[1:]:
        try:
            out[norm(r[ni])] = int(round(float(r[ci])))
        except (IndexError, ValueError):
            continue
    return out


def closure_for(name, closures):
    c = closures.get(name) or next((v for k, v in closures.items() if norm(k) == norm(name)), None)
    if not c:
        return {"status": "unknown", "checked": None, "order_url": None, "note": None}
    st = c.get("status") if c.get("status") in STATUS else "unknown"
    url = c.get("order_url")
    if url and not str(url).startswith("https://"):
        url = None                  # the page only ever links https agency pages
    return {"status": st, "checked": c.get("checked"), "order_url": url, "note": c.get("note")}


# ---------------------------------------------------------------- build
def prop(p, *keys):
    for k in keys:
        if p.get(k) not in (None, ""):
            return p[k]
    return None


def when(v):
    """WFIGS dates come back as epoch milliseconds in GeoJSON; tolerate ISO strings too."""
    if v is None:
        return None
    try:
        return datetime.datetime.fromtimestamp(float(v) / 1000, datetime.timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return str(v)[:10]


def build(features, year, closures, exclude, conifer, tol=0.0008, min_ring_acres=40):
    skip = {norm(x["name"]): x.get("reason", "") for x in exclude if x.get("name")}
    best = {}
    for f in features:
        p = f.get("properties") or {}
        name = (prop(p, "poly_IncidentName", "attr_IncidentName") or "").strip()
        if not name:
            continue
        name = " ".join(w if w.isupper() and len(w) <= 3 else w.capitalize() for w in name.split())
        key = norm(name) + "|" + str(prop(p, "attr_UniqueFireIdentifier", "poly_IRWINID") or "")
        acres = float(prop(p, "poly_GISAcres", "attr_IncidentSize") or 0)
        if key in best and best[key]["acres"] >= acres:
            continue                # WFIGS can carry more than one perimeter per fire; keep the largest
        best[key] = {"name": name, "acres": acres, "props": p, "geom": f.get("geometry")}
    fires, dropped = [], []
    for v in sorted(best.values(), key=lambda x: -x["acres"]):
        n = norm(v["name"])
        if n in skip:
            dropped.append({"name": v["name"], "reason": skip[n]})
            continue
        polys = clean_polys(v["geom"], tol, min_ring_acres)
        if not polys:
            continue
        p = v["props"]
        fires.append({
            "name": v["name"],
            "acres": int(round(v["acres"])),
            "conifer_acres": conifer.get(n),
            "start": when(prop(p, "attr_FireDiscoveryDateTime")),
            "owner": prop(p, "attr_POOLandownerKind", "attr_POOLandownerCategory"),
            "closure": closure_for(v["name"], closures),
            "polys": polys,
        })
    return {
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "year": year,
        "source": "NIFC WFIGS interagency wildfire perimeters (public)",
        "note": "Perimeters only. A burned area is not automatically open, safe or productive.",
        "fires": fires,
        "excluded": len(dropped),
    }, dropped


def atomic_write(path, obj):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".burns-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--min-acres", type=int, default=1000)
    ap.add_argument("--state", default="US-OR", help="WFIGS point-of-origin state; empty string to turn off")
    ap.add_argument("--fixture", help="read GeoJSON features from this file instead of WFIGS")
    ap.add_argument("--conifer", default=os.path.join(PASS_DIR, "conifer.csv"))
    ap.add_argument("--out", default=SITE_DATA + "/c/burns.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.fixture:
        with open(a.fixture) as f:
            feats = json.load(f).get("features", [])
    else:
        feats = query_wfigs(a.year, a.min_acres, a.state)
    closures = _load_json(os.path.join(PASS_DIR, "closures.json"), {})
    exclude = _load_json(os.path.join(PASS_DIR, "exclude.json"), [])
    out, dropped = build(feats, a.year, closures, exclude, load_conifer(a.conifer))

    total = sum(f["acres"] for f in out["fires"])
    print("%d fires, %s acres, %d excluded%s" % (len(out["fires"]), format(total, ","), len(dropped),
          "" if not dropped else " (" + ", ".join(d["name"] for d in dropped) + ")"), file=sys.stderr)
    unk = [f["name"] for f in out["fires"] if f["closure"]["status"] == "unknown"]
    if unk:
        print("no closure entry yet: " + ", ".join(unk[:15]) + (" ..." if len(unk) > 15 else ""), file=sys.stderr)
    if a.dry_run:
        return 0
    if not out["fires"]:
        print("refusing to write an empty layer over the old one", file=sys.stderr)
        return 1
    atomic_write(a.out, out)
    print("wrote " + a.out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
