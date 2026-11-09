"""Re-scores 2016-2025 history for every listed zone with a changed species registry and/or scorer, in an isolated root, so the change can
be checked against public finds (analysis/val2.py) before it goes live. Production files are only read (weather caches via symlinks).
usage (on the VPS, as the build user):  python3 run_variant_test.py <variant> <out.json>
Variants:
  base        unchanged (control: must reproduce production exactly)
  kf_nov      fall king coastal season ends in November (public guides: Sept-Nov; public reports P90 Nov 13)
  ch_open1    chanterelle season opener at 1.0 in of rain in 7 days instead of 1.5 (public guides: fruiting follows the first fall rains)
  ch_frost14  chanterelle: any frost night (28 F or colder) in the last 14 days halves the score; the 1-night frost penalty applies to 1 or
              more nights (it only fired at exactly 1); public guides: the season ends with the first frosts
  all         the three changes together
  ch_aug      chanterelle inland season also opens in August (public guides: mid-summer start at higher elevations; reports P10 Aug 17)
"""
import importlib, json, os, shutil, sys

variant, out = sys.argv[1], sys.argv[2]
ROOT = "/opt/shrooms-test/var_" + variant
for d in ("cache", "data", "site/data", "scout"):
    os.makedirs(ROOT + "/" + d, exist_ok=True)
for f in os.listdir("/opt/shrooms/cache"):
    if f.startswith("arch"):
        dst = ROOT + "/cache/" + f
        if not os.path.lexists(dst):
            os.symlink("/opt/shrooms/cache/" + f, dst)
for f in ("zones_extra.json", "permits_extra.json"):
    shutil.copy("/opt/shrooms/" + f, ROOT + "/" + f)
for sub in ("scripts", "references"):
    if os.path.exists(ROOT + "/scout/" + sub):
        shutil.rmtree(ROOT + "/scout/" + sub)
    shutil.copytree("/opt/mushroom-scout/" + sub, ROOT + "/scout/" + sub)
os.makedirs(ROOT + "/scout/cache", exist_ok=True)

reg_path = ROOT + "/scout/references/species_registry.json"
reg = json.load(open(reg_path))
sp = reg["species"]
score_path = ROOT + "/scout/scripts/score.py"
score_src = open(score_path).read()
builder_src = open("/opt/shrooms/shrooms_build.py").read()

want = {"kf_nov", "ch_open1", "ch_frost14"} if variant == "all" else {variant}
if "ch_aug" in want:
    sp["chanterelle"]["months_interior"] = [8, 9, 10, 11]
if "kf_nov" in want:
    sp["king_fall"]["months_coastal"] = [9, 10, 11]
if "ch_open1" in want:
    sp["chanterelle"]["trigger"]["opener_rule"]["rolling_7d_precip_in"] = 1.0
if "ch_frost14" in want:
    sp["chanterelle"]["penalties"]["frost_28F_last14d"] = 0.5
    if "frost_nights_last14" in builder_src:
        want.discard("ch_frost14")
if "ch_frost14" in want:
    old = "        if frost_3d == 1:\n            score *= penalties['single_frost_28F']"
    assert old in score_src
    score_src = score_src.replace(old, "        if frost_3d >= 1:\n            score *= penalties['single_frost_28F']")
    old2 = "    # Heat penalty"
    assert old2 in score_src
    score_src = score_src.replace(old2, "    if 'frost_28F_last14d' in penalties and weather.get('frost_nights_last14', 0) > 0:\n"
                                        "        score *= penalties['frost_28F_last14d']\n"
                                        "        negatives.append(f\"frost in the last 14 days\")\n\n" + old2, 1)
    old3 = '        "frost_nights_last5": sum(1 for t in win(tmin, 5) if (t if t is not None else 100) <= 28),'
    assert old3 in builder_src
    builder_src = builder_src.replace(old3, old3 + '\n        "frost_nights_last14": sum(1 for t in win(tmin, 14) if (t if t is not None else 100) <= 28),')
json.dump(reg, open(reg_path, "w"), indent=1)
open(score_path, "w").write(score_src)
open(ROOT + "/shrooms_build_test.py", "w").write(builder_src)

os.environ["SHROOMS_ROOT"] = ROOT
os.environ["SHROOMS_SITE_DATA"] = ROOT + "/site/data"
os.environ["SHROOMS_SKILL"] = ROOT + "/scout"
sys.path.insert(0, ROOT)
sys.path.insert(1, "/opt/shrooms")
b = importlib.import_module("shrooms_build_test")
assert b.SCRIPTS.startswith(ROOT), b.SCRIPTS
reg2 = b.sc.load_registry()
zones, zx, px = b.all_zones()
series = b.prune_series(b.run_backfill(reg2, zones, list(range(2016, 2026)), None, False))
json.dump(series, open(out, "w"))
print(variant, "series", len(series))
