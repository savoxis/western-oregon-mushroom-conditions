"""Fetch the 'effort' background for the validation: every public human observation of mushroom-type fungi (class
Agaricomycetes) in Oregon, 2016-2025, from GBIF, minus the four target genera. Split by year and month, fetched in parallel.
Compact output: [date, lat, lon, genus]."""
import json, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

OUT = sys.argv[1]
SKIP = {"Cantharellus", "Morchella", "Boletus", "Craterellus"}


def get(q):
    url = "https://api.gbif.org/v1/occurrence/search?" + urllib.parse.urlencode(q)
    for a in range(6):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "shrooms-validation/1.0"}), timeout=90))
        except Exception:
            time.sleep(3 * (a + 1))
    return None


def month(ym):
    y, m = ym
    rows, off, seen = [], 0, 0
    while True:
        q = {"taxonKey": 186, "country": "US", "stateProvince": "Oregon", "hasCoordinate": "true", "hasGeospatialIssue": "false",
             "basisOfRecord": "HUMAN_OBSERVATION", "occurrenceStatus": "PRESENT", "year": y, "month": m, "limit": 300, "offset": off}
        d = get(q)
        if d is None:
            return ym, rows, seen, False
        for r in d.get("results", []):
            seen += 1
            ed = str(r.get("eventDate") or "")[:10]
            if len(ed) != 10 or r.get("decimalLatitude") is None:
                continue
            g = r.get("genus") or ""
            if g in SKIP:
                continue
            unc = r.get("coordinateUncertaintyInMeters")
            if unc is not None and unc > 2000:
                continue
            rows.append([ed, round(r["decimalLatitude"], 3), round(r["decimalLongitude"], 3), g])
        off += 300
        if d.get("endOfRecords"):
            return ym, rows, seen, True
        time.sleep(0.2)


jobs = [(y, m) for y in range(2016, 2026) for m in range(1, 13)]
allrows, seen, bad = [], 0, []
with ThreadPoolExecutor(max_workers=5) as ex:
    for n, (ym, rows, s, ok) in enumerate(ex.map(month, jobs), 1):
        allrows += rows; seen += s
        if not ok:
            bad.append(ym)
        if n % 12 == 0:
            print(n, "of", len(jobs), "months;", seen, "seen,", len(allrows), "kept", flush=True)
json.dump({"seen": seen, "rows": allrows, "failed_months": bad}, open(OUT, "w"), separators=(",", ":"))
print("done", seen, len(allrows), "failed", bad)
