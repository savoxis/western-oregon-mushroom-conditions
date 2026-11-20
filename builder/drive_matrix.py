#!/usr/bin/env python3
"""Regenerates builder/drive_from.json: approximate road miles from each starting city on the page's "driving from"
picker to every zone. Run it by hand when a zone is added or a starting city changes; the nightly build only reads the file.

How: one request to the public OSRM routing demo server (router.project-osrm.org, free, fair use) for the road distance between
each city and each zone centre. Only coordinates of towns and mountain areas go out. A road distance is kept only when it is
believable against the straight line (1.05 to 3 times as long); a zone centre that snapped to a faraway road is left out
and the builder falls back to straight line x 1.35. Portland is not in the file: its times are hand-entered in zones_extra.json.
The builder turns miles into hours at drive_avg_mph (55), which matched the hand-entered Portland times to about 15 minutes.

usage:  python builder/drive_matrix.py            (from a repo checkout or the server; SHROOMS_SKILL / SHROOMS_ROOT as for the builder)
        python builder/drive_matrix.py --dry      print what would change, write nothing"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if not os.environ.get("SHROOMS_SKILL") and os.path.isdir(os.path.join(REPO, "scout")):
    os.environ["SHROOMS_SKILL"] = os.path.join(REPO, "scout")
if not os.path.isdir(os.environ.get("SHROOMS_ROOT", "/opt/shrooms")):
    os.environ["SHROOMS_ROOT"] = HERE
sys.path.insert(0, HERE)
import shrooms_build as B  # noqa: E402

OUT = os.path.join(HERE, "drive_from.json")
SERVER = "https://router.project-osrm.org"
M_PER_MI = 1609.344

# id, label shown on the page, town centre. Portland (the default) is first and is not routed: see the docstring.
ORIGINS = [
    ("portland", "Portland", 45.5152, -122.6784),
    ("bend", "Bend", 44.0582, -121.3153),
    ("eugene", "Eugene", 44.0521, -123.0868),
    ("coosbay", "Coos Bay", 43.3665, -124.2179),
    ("medford", "Medford", 42.3265, -122.8756),
    ("johnday", "John Day", 44.4152, -118.9530),
    ("lagrande", "La Grande", 45.3246, -118.0877),
]


def main():
    dry = "--dry" in sys.argv[1:]
    zones, zx, _px = B.all_zones()
    routed = [o for o in ORIGINS if o[0] != "portland"]
    coords = ["%.5f,%.5f" % (o[3], o[2]) for o in routed] + ["%.5f,%.5f" % (z["lon"], z["lat"]) for z in zones]
    url = "%s/table/v1/driving/%s?sources=%s&destinations=%s&annotations=distance" % (
        SERVER, ";".join(coords), ";".join(str(i) for i in range(len(routed))),
        ";".join(str(len(routed) + i) for i in range(len(zones))))
    req = urllib.request.Request(url, headers={"User-Agent": "shrooms-drive-matrix/1"})
    with urllib.request.urlopen(req, timeout=90) as r:
        res = json.load(r)
    if res.get("code") != "Ok":
        raise SystemExit("routing server said: %s" % res.get("code"))
    miles, dropped = {}, []
    for oi, o in enumerate(routed):
        row = {}
        for zi, z in enumerate(zones):
            d = res["distances"][oi][zi]
            if d is None:
                dropped.append((o[0], z["id"], "no route"))
                continue
            mi = d / M_PER_MI
            line = B.haversine_km(o[2], o[3], z["lat"], z["lon"]) * 0.621371
            if line < 1 or not (1.05 <= mi / line <= 3.0):
                dropped.append((o[0], z["id"], "%.0f road mi vs %.0f straight" % (mi, line)))
                continue
            row[z["id"]] = round(mi)
        miles[o[0]] = row
    doc = {
        "_comment": "Approximate road miles from each starting city to each zone, made by builder/drive_matrix.py from the public OSRM "
                    "routing demo server. Hours = miles / drive_avg_mph (zones_extra.json), nearest quarter hour, always shown with a ~. "
                    "Portland is not here: its times are hand-entered in zones_extra.json. A zone missing from a city's list falls back to "
                    "straight line x 1.35. Regenerate by hand when zones change.",
        "origins": [{"id": o[0], "name": o[1], "lat": o[2], "lon": o[3]} for o in ORIGINS],
        "road_miles": miles,
    }
    print("zones %d, cities %d, dropped %d" % (len(zones), len(routed), len(dropped)))
    for d in dropped:
        print("  dropped %s -> %s (%s)" % d)
    if dry:
        return 0
    with open(OUT, "w", newline="\n") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
