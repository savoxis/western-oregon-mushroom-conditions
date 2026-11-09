"""Past finds for shrooms.strong.beer: public human-observation records (GBIF, mostly iNaturalist research grade) of the four
target mushrooms in Oregon, tagged with the land manager at each spot (PAD-US) and exported as a compact file for the map.
Stdlib only. Called by shrooms_build.py (modes 'sightings', 'nightly', 'auto'); can also be run alone for testing:
    SHROOMS_ROOT=... SHROOMS_SITE_DATA=... python shrooms_sightings.py [full|refresh|tag|export] [--minutes N]
Only date, rounded location, species and the GBIF record id are kept: no photos, no observer names.
"""
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

GBIF = "https://api.gbif.org/v1/occurrence/search"
PAD = "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/Manager_Name/FeatureServer/0/query"
UA = {"User-Agent": "shrooms.strong.beer (mushroom conditions site, low-volume nightly job)"}
# (site species key, GBIF taxon key, species epithets to skip). iNaturalist itself bans this server's IP range, so GBIF
# (which republishes iNaturalist research-grade records, about a week or two behind) is the source.
TAXA = [
    ("chanterelle", 9623860, ("cinnabarinus", "lateritius")),   # genus Cantharellus, minus the cinnabar and smooth chanterelles
    ("morel_natural", 2594601, ()),                             # genus Morchella (burn and natural morels are the same genus)
    ("king_spring", 6016634, ()),                               # Boletus rex-veris
    ("king_fall", 5954958, ()),                                 # Boletus edulis
]
SPECIES = [t[0] for t in TAXA]
SINCE_YEAR = 2010
MAX_ACC_M = 2000
LAND_LABELS = {
    "f": "National forest", "b": "BLM land", "s": "State land",
    "l": "County, city, research or other (check rules)", "r": "No-picking or restricted area", "p": "Private or not mapped",
}
RESTRICT_DES = {"WA", "SW", "RNA", "NSBV", "NP", "NM", "NWR", "SP", "REA", "NLS"}   # wilderness, botanical/scenic, RNA, parks, refuges
STATE_OPEN = {"SDNR", "SDOL", "SLB", "SDC"}
NO_PICK_MGR = {"NPS", "FWS", "SPR", "SFW", "DOD", "USBR", "USACE", "DOE", "BOEM", "NOAA"}


def _log(log, msg):
    (log or print)(msg)


def init(con):
    con.execute("CREATE TABLE IF NOT EXISTS sightings (id INTEGER PRIMARY KEY, sp TEXT, date TEXT, lat REAL, lon REAL, acc INTEGER, "
                "land TEXT, seen TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS land_cache (k TEXT PRIMARY KEY, cls TEXT, unit TEXT, checked TEXT)")
    con.commit()


def _get(url, tries=6):
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            time.sleep(8 * (a + 1) if exc.code in (429, 502, 503, 504) else 3)
            if exc.code in (400, 404):
                return None
        except Exception:
            time.sleep(3 * (a + 1))
    return None


def fetch_taxon(taxon_key, skip, since=None, log=None):
    """Yields dicts for every usable Oregon human-observation record of one taxon (GBIF offset paging)."""
    off = 0
    this_year = datetime.now(timezone.utc).year
    while True:
        q = {"taxonKey": taxon_key, "country": "US", "stateProvince": "Oregon", "hasCoordinate": "true", "hasGeospatialIssue": "false",
             "occurrenceStatus": "PRESENT", "basisOfRecord": "HUMAN_OBSERVATION", "year": "%d,%d" % (SINCE_YEAR, this_year),
             "limit": 300, "offset": off}
        if since:
            q["lastInterpreted"] = since
        d = _get(GBIF + "?" + urllib.parse.urlencode(q))
        time.sleep(0.5)
        if d is None:
            _log(log, "sightings: GBIF request failed for taxon %s at offset %s; will retry next run" % (taxon_key, off))
            return
        for r in d.get("results", []):
            ed = str(r.get("eventDate") or "")
            day = ed[:10]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", day) or ("/" in ed and ed.split("/")[0][:10] != ed.split("/")[1][:10]):
                continue
            acc = r.get("coordinateUncertaintyInMeters")
            if acc is not None and acc > MAX_ACC_M:
                continue
            lat, lon = r.get("decimalLatitude"), r.get("decimalLongitude")
            if lat is None or lon is None:
                continue
            name = (r.get("species") or r.get("scientificName") or "").lower()
            if any(s in name for s in skip):
                continue
            yield {"id": r["key"], "date": day, "lat": round(float(lat), 4), "lon": round(float(lon), 4), "acc": None if acc is None else int(acc)}
        off += 300
        if d.get("endOfRecords") or off >= 30000:
            return


def refresh(con, full=False, log=None):
    """Full load (first run or --full) or an incremental pass over records changed in the last 10 days."""
    init(con)
    have = con.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
    since = None
    if have and not full:                                       # records GBIF (re)processed in the last 10 days
        since = "%s,%s" % ((datetime.now(timezone.utc) - timedelta(days=10)).strftime("%F"),
                           (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%F"))
    now = datetime.now(timezone.utc).strftime("%F")
    added = 0
    for sp, tid, skip in TAXA:
        n = 0
        for r in fetch_taxon(tid, skip, since, log):
            con.execute("INSERT INTO sightings (id, sp, date, lat, lon, acc, land, seen) VALUES (?,?,?,?,?,?,NULL,?) "
                        "ON CONFLICT(id) DO UPDATE SET sp=excluded.sp, date=excluded.date, acc=excluded.acc, seen=excluded.seen, "
                        "land=CASE WHEN sightings.lat=excluded.lat AND sightings.lon=excluded.lon THEN sightings.land ELSE NULL END, "
                        "lat=excluded.lat, lon=excluded.lon",
                        (r["id"], sp, r["date"], r["lat"], r["lon"], r["acc"], now))
            n += 1
        con.commit()
        added += n
        _log(log, "sightings: %s %s records %s" % (sp, n, "(incremental)" if since else "(full)"))
    return added


def classify(feats):
    """feats = PAD-US attribute dicts at one point. Returns (class letter, unit name)."""
    fee = [f for f in feats if f.get("Category") == "Fee"]
    des = [f for f in feats if f.get("Category") == "Designation"]
    for f in des + fee:
        if f.get("Des_Tp") in RESTRICT_DES or f.get("Pub_Access") == "XA":
            return "r", f.get("Unit_Nm") or ""
    if not fee:
        return "p", ""
    mg = {f.get("Mang_Name") for f in fee}
    unit = next((f.get("Unit_Nm") or "" for f in fee if f.get("Mang_Name") in ("USFS", "BLM")), fee[0].get("Unit_Nm") or "")
    if "USFS" in mg:
        c = "f"
    elif "BLM" in mg:
        c = "b"
    elif mg & STATE_OPEN:
        c = "s"
    elif mg & NO_PICK_MGR:
        return "r", unit
    else:
        return "l", unit
    if all(f.get("Pub_Access") == "RA" for f in fee):
        return "l", unit
    return c, unit


def land_at(lat, lon):
    q = {"where": "1=1", "geometry": "%s,%s" % (lon, lat), "geometryType": "esriGeometryPoint", "inSR": 4326,
         "spatialRel": "esriSpatialRelIntersects", "outFields": "Category,Mang_Name,Des_Tp,Unit_Nm,Pub_Access",
         "returnGeometry": "false", "f": "json"}
    d = _get(PAD + "?" + urllib.parse.urlencode(q), tries=4)
    if not d or "features" not in d:
        return None
    return classify([f["attributes"] for f in d["features"]])


def pending(con):
    init(con)
    return con.execute("SELECT COUNT(*) FROM sightings WHERE land IS NULL").fetchone()[0]


def tag(con, minutes=20, log=None):
    """Fills in the land class of records that have none, ~0.3 s per new ~100 m cell, stopping after `minutes`."""
    init(con)
    end = time.time() + minutes * 60
    done = 0
    today = datetime.now(timezone.utc).strftime("%F")
    rows = con.execute("SELECT id, lat, lon FROM sightings WHERE land IS NULL").fetchall()
    fails = 0
    for sid, lat, lon in rows:
        if time.time() > end or fails >= 8:
            break
        k = "%.3f,%.3f" % (lat, lon)
        hit = con.execute("SELECT cls FROM land_cache WHERE k=?", (k,)).fetchone()
        if hit:
            cls = hit[0]
        else:
            res = land_at(float(k.split(",")[0]), float(k.split(",")[1]))
            time.sleep(0.3)
            if res is None:
                fails += 1
                continue
            fails = 0
            cls = res[0]
            con.execute("INSERT OR REPLACE INTO land_cache VALUES (?,?,?,?)", (k, res[0], res[1], today))
        con.execute("UPDATE sightings SET land=? WHERE id=?", (cls, sid))
        done += 1
        if done % 100 == 0:
            con.commit()
    con.commit()
    _log(log, "sightings: tagged land for %d records, %d still pending" % (done, pending(con)))
    return done


def export(con, out_path, log=None):
    init(con)
    rows = con.execute("SELECT id, sp, date, lat, lon, land FROM sightings ORDER BY date, id").fetchall()
    sp_idx = {s: i for i, s in enumerate(SPECIES)}
    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "species": SPECIES, "land": LAND_LABELS, "n": len(rows),
        "pending_land": sum(1 for r in rows if r[5] is None),
        "source": "Public observation records via GBIF, mostly iNaturalist research grade (CC licensed); land manager from USGS PAD-US",
        "rows": [[r[0], sp_idx[r[1]], r[2], round(r[3], 3), round(r[4], 3), r[5] or "?"] for r in rows if r[1] in sp_idx],
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    os.replace(tmp, out_path)
    _log(log, "sightings: exported %d records (%d without a land class yet)" % (len(data["rows"]), data["pending_land"]))


def run(con, site_data, full=False, minutes=20, log=None):
    """Refresh (full when the table is empty), tag land, export. Never raises into the nightly build."""
    init(con)
    try:
        refresh(con, full=full or con.execute("SELECT COUNT(*) FROM sightings").fetchone()[0] == 0, log=log)
    except Exception as exc:
        _log(log, "sightings: refresh failed: %r" % exc)
    try:
        tag(con, minutes=minutes, log=log)
    except Exception as exc:
        _log(log, "sightings: land tagging failed: %r" % exc)
    export(con, site_data + "/c/sightings.json", log)


def main():
    root = os.environ.get("SHROOMS_ROOT", "/opt/shrooms")
    site = os.environ.get("SHROOMS_SITE_DATA", root + "/site/data")
    argv = sys.argv[1:]
    mode = argv[0] if argv else "refresh"
    minutes = int(argv[argv.index("--minutes") + 1]) if "--minutes" in argv else 20
    os.makedirs(root + "/data", exist_ok=True)
    con = sqlite3.connect(root + "/data/live_history.sqlite", timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    if mode == "tag":
        tag(con, minutes)
    elif mode == "export":
        export(con, site + "/c/sightings.json")
    else:
        run(con, site, full=(mode == "full"), minutes=minutes)


if __name__ == "__main__":
    main()
