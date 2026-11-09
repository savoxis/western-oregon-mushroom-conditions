"""Sample LANDFIRE 2024 (public domain, USGS) forest structure at every past-find location and on a grid around every zone.
Layers: SClass (succession class), EVH (existing vegetation height), EVC (cover), EVT (type code). Batch getSamples, ~0.5 s per 500 points.
usage: python hab_fetch.py sightings.json zones_all.json zones_extra.json out.json"""
import json, math, sys, time, urllib.parse, urllib.request

LAYERS = ["SClass", "EVH", "EVC", "EVT"]
BASE = "https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2024/LF2024_%s_CONUS/ImageServer/getSamples"


def samples(layer, pts):
    q = {"geometry": json.dumps({"points": pts, "spatialReference": {"wkid": 4326}}), "geometryType": "esriGeometryMultipoint",
         "returnFirstValueOnly": "true", "f": "json"}
    for a in range(5):
        try:
            r = urllib.request.urlopen(urllib.request.Request(BASE % layer, data=urllib.parse.urlencode(q).encode()), timeout=120)
            d = json.loads(r.read().decode())
            vals = {s["locationId"]: s["value"] for s in d["samples"]}
            return [vals.get(i, "NoData") for i in range(len(pts))]
        except Exception as e:
            time.sleep(5 * (a + 1))
    return ["Err"] * len(pts)


sj = json.load(open(sys.argv[1]))
zones = json.load(open(sys.argv[2])) + json.load(open(sys.argv[3]))["zones"]
pts = {}
for r in sj["rows"]:
    pts[(round(r[3], 3), round(r[4], 3))] = 1
kind = {}
for z in zones:                                   # 5 x 5 grid, 3 km apart (about +-6 km) around each zone center
    for i in range(-2, 3):
        for j in range(-2, 3):
            la = round(z["lat"] + i * 3 / 111.2, 3)
            lo = round(z["lon"] + j * 3 / (111.2 * math.cos(math.radians(z["lat"]))), 3)
            pts.setdefault((la, lo), 1)
            kind.setdefault(z["id"], []).append("%s,%s" % (la, lo))
keys = list(pts)
print(len(keys), "points", flush=True)
out = {"%s,%s" % k: {} for k in keys}
for layer in LAYERS:
    for s in range(0, len(keys), 400):
        chunk = keys[s:s + 400]
        vals = samples(layer, [[k[1], k[0]] for k in chunk])
        for k, v in zip(chunk, vals):
            out["%s,%s" % k][layer] = v
        time.sleep(0.3)
    print(layer, "done", flush=True)
json.dump({"points": out, "zone_grids": kind}, open(sys.argv[4], "w"), separators=(",", ":"))
