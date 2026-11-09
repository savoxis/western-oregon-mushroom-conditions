"""Re-scores the 2016-2025 history of every listed zone with a seasonal soil-temperature correction added to the ERA5-Land soil temperature
before the (unchanged) skill scorer runs. Runs in an isolated root; production files are only read (weather caches via symlinks).
usage: python3 run_offset_test.py full|half|none out.json"""
import importlib, json, os, sys

variant, out = sys.argv[1], sys.argv[2]
ROOT = "/opt/shrooms-test/" + variant
os.makedirs(ROOT + "/cache", exist_ok=True)
os.makedirs(ROOT + "/data", exist_ok=True)
os.makedirs(ROOT + "/site/data", exist_ok=True)
for f in os.listdir("/opt/shrooms/cache"):
    if f.startswith("arch"):
        dst = ROOT + "/cache/" + f
        if not os.path.lexists(dst):
            os.symlink("/opt/shrooms/cache/" + f, dst)
for f in ("zones_extra.json", "permits_extra.json"):
    if not os.path.exists(ROOT + "/" + f):
        open(ROOT + "/" + f, "w").write(open("/opt/shrooms/" + f).read())
os.environ["SHROOMS_ROOT"] = ROOT
os.environ["SHROOMS_SITE_DATA"] = ROOT + "/site/data"

FULL = {1: 0.0, 2: 0.0, 3: 5.0, 4: 6.0, 5: 3.5, 6: 2.5, 7: 0.0, 8: 0.0, 9: 2.0, 10: 4.0, 11: 5.0, 12: 0.0}      # pooled SNOTEL bias by month, rounded
scale = {"full": 1.0, "half": 0.5, "none": 0.0}[variant]
OFF = {m: v * scale for m, v in FULL.items()}

src = open("/opt/shrooms/shrooms_build.py").read()
old = "soil_t = [soil_t_d.get(d) for d in dates]"
assert src.count(old) == 1
src = src.replace(old, "soil_t = [(soil_t_d.get(d) + OFFSETS.get(int(d[5:7]), 0.0)) if soil_t_d.get(d) is not None else None for d in dates]")
src = "OFFSETS = %r\n" % (OFF,) + src
open(ROOT + "/shrooms_build_test.py", "w").write(src)
sys.path.insert(0, ROOT)
sys.path.insert(1, "/opt/shrooms")
b = importlib.import_module("shrooms_build_test")
reg = b.sc.load_registry()
zones, zx, px = b.all_zones()
years = list(range(2016, 2026))
allser = b.run_backfill(reg, zones, years, None, False)
series = b.prune_series(allser)
json.dump(series, open(out, "w"))
print(variant, "series", len(series), "offsets", OFF)
