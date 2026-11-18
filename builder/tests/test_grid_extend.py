"""Offline checks for grid_extend.py (heat-map sample points east of the Cascades). No network: LANDFIRE and elevation are faked.
    cd /opt/shrooms && python3 -B tests/test_grid_extend.py
Writes only to a temporary directory."""
import json, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, "/opt/shrooms")
import grid_extend as G  # noqa: E402
import burns_2027 as B  # noqa: E402

# a square "Oregon" from -124 to -117 lon, 42 to 46 lat
SQUARE = [[[[-124, 42], [-117, 42], [-117, 46], [-124, 46], [-124, 42]]]]


def put(path, obj):
    with open(path, "w") as fh:
        fh.write(obj if isinstance(obj, str) else json.dumps(obj))


def get(path):
    with open(path) as fh:
        return json.load(fh)


def western_grid(oregon, km=35):
    pts = []
    for i, (la, lo) in enumerate(G.lattice(oregon, {"lat": 44.0, "lon": -122.0}, km)):
        if lo < -120.6:
            side = "east" if G.is_east(la, lo) else "west"
            pts.append({"id": "g_%03d" % i, "lat": la, "lon": lo, "elev_ft": 2000, "side": side, "coastal": lo < -123.6,
                        "species": ["morel_natural", "king_spring"] if side == "east" else ["chanterelle", "king_fall"], "lite": True})
    return pts


def forest_east_of(lon_cut):
    """Fake LANDFIRE: tree cover (EVC 150) east of lon_cut, sagebrush (EVC 0) west of it."""
    return lambda spots: [150 if lo > lon_cut else 0 for _, lo in spots]


class Lattice(unittest.TestCase):
    def test_spacing_is_measured(self):
        g = western_grid(SQUARE)
        self.assertAlmostEqual(G.spacing_km(g), 35, delta=2)

    def test_crest(self):
        self.assertTrue(G.is_east(44.3, -120.0))        # Prineville country
        self.assertFalse(G.is_east(44.3, -122.5))       # McKenzie valley
        self.assertFalse(G.is_east(45.37, -121.7))      # Mt. Hood itself is crest, not east

    def test_no_new_point_on_top_of_an_old_one(self):
        g = western_grid(SQUARE)
        new, _ = G.plan(g, SQUARE, 35, 30, evc_fn=forest_east_of(-200), elev_fn=lambda s: [4000] * len(s))
        self.assertTrue(new)
        for p in new:
            self.assertGreater(min(G.hav(p["lat"], p["lon"], q["lat"], q["lon"]) for q in g), 0.75 * 35, p["id"])
            self.assertTrue(B.in_polys(p["lon"], p["lat"], SQUARE))


class Forest(unittest.TestCase):
    def test_only_forest_spots_are_kept(self):
        g = western_grid(SQUARE)
        new, rejected = G.plan(g, SQUARE, 35, 30, evc_fn=forest_east_of(-119.0), elev_fn=lambda s: [4500] * len(s))
        self.assertTrue(new and rejected)
        for p in new:
            self.assertGreater(p["lon"], -119.1, p["id"])
            self.assertGreaterEqual(p["_forest_pct"], 30)
        self.assertTrue(all("forest" in why for _, _, why in rejected))

    def test_landfire_gaps_are_not_counted_as_forest(self):
        g = western_grid(SQUARE)
        new, rejected = G.plan(g, SQUARE, 35, 30, evc_fn=lambda s: [None] * len(s), elev_fn=lambda s: [4500] * len(s))
        self.assertEqual(new, [])
        self.assertTrue(all(why == "no LANDFIRE answer" for _, _, why in rejected))

    def test_share(self):
        self.assertEqual(G.forest_share([150] * 10 + [0] * 15, 1), [40])
        self.assertEqual(G.forest_share([150] * 5 + [None] * 20, 1), [None])


class Points(unittest.TestCase):
    def setUp(self):
        self.g = western_grid(SQUARE)
        self.new, _ = G.plan(self.g, SQUARE, 35, 30, evc_fn=forest_east_of(-200), elev_fn=lambda s: [5120] * len(s))

    def test_fields_copied_from_an_east_side_point(self):
        keys = set(self.g[0])
        for p in self.new:
            self.assertEqual(set(p) - {"_forest_pct"}, keys, p["id"])
            self.assertTrue(p["id"].startswith("g_"))
            self.assertEqual(p["side"], "east")
            self.assertFalse(p["coastal"])
            self.assertEqual(p["species"], ["morel_natural", "king_spring"])
            self.assertTrue(p["lite"])
            self.assertEqual(p["elev_ft"], 5120)
            self.assertTrue(all(ord(c) < 128 for c in json.dumps(p)))

    def test_ids_unique(self):
        ids = [p["id"] for p in self.g + self.new]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_east_template_falls_back_to_spring_species(self):
        west_only = [dict(p, side="west", species=["chanterelle"]) for p in self.g]
        new, _ = G.plan(west_only, SQUARE, 35, 30, evc_fn=forest_east_of(-200), elev_fn=lambda s: [4000] * len(s))
        self.assertTrue(new)
        self.assertTrue(all(p["species"] == ["morel_natural", "king_spring"] and p["side"] == "east" for p in new))

    def test_real_outline(self):
        path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "site", "oregon.json")
        if not os.path.exists(path):
            self.skipTest("site/oregon.json not next to the builder")
        o = B.load_oregon(path)
        g = western_grid(o)
        new, _ = G.plan(g, o, 35, 30, evc_fn=forest_east_of(-200), elev_fn=lambda s: [4000] * len(s))
        self.assertLess(len(new), 130)                  # all of eastern Oregon, if every spot were forest
        self.assertTrue(all(B.in_polys(p["lon"], p["lat"], o) for p in new))


class Drops(unittest.TestCase):
    BANDS = {"morel_natural": {"5": [3000, 4800]}, "king_spring": {"all": [3000, 6500]}, "chanterelle": {"all": [0, 4000]}}

    def run_plan(self, elev, **kw):
        g = western_grid(SQUARE)
        return G.plan(g, SQUARE, 35, 30, evc_fn=forest_east_of(-200), elev_fn=lambda s: [elev] * len(s), bands=self.BANDS, **kw)

    def test_water_level(self):
        new, rej = self.run_plan(0)
        self.assertEqual(new, [])
        self.assertTrue(all(why == "at water level" for _, _, why in rej))

    def test_above_every_band(self):
        new, rej = self.run_plan(7470)
        self.assertEqual(new, [])
        self.assertTrue(all("outside every species band" in why for _, _, why in rej))

    def test_inside_a_band_is_kept(self):
        new, _ = self.run_plan(6200)
        self.assertTrue(new)

    def test_skip_by_id(self):
        all_new, _ = self.run_plan(4500)
        drop = {all_new[0]["id"], all_new[1]["id"]}
        new, rej = self.run_plan(4500, skip=drop)
        self.assertEqual(len(new), len(all_new) - 2)
        self.assertFalse(drop & {p["id"] for p in new})
        self.assertEqual(sum(1 for _, _, why in rej if why == "skipped by hand"), 2)

    def test_real_registry_bands(self):
        b = G.load_bands()
        if not b:
            self.skipTest("species_registry.json not found")
        self.assertFalse(G.scorable({"species": ["morel_natural", "king_spring"], "elev_ft": 7470}, b))
        self.assertTrue(G.scorable({"species": ["morel_natural", "king_spring"], "elev_ft": 5200}, b))
        self.assertTrue(G.scorable({"species": ["chanterelle", "king_fall"], "elev_ft": 140}, b))


class Write(unittest.TestCase):
    def test_backup_then_append(self):
        g = western_grid(SQUARE)
        new, _ = G.plan(g, SQUARE, 35, 30, evc_fn=forest_east_of(-118.5), elev_fn=lambda s: [4000] * len(s))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "grid.json")
            put(path, {"points": g, "other": 1})
            bak = G.write_grid({"points": g, "other": 1}, new, path)
            self.assertEqual(get(bak)["points"], g)
            out = get(path)
            self.assertEqual(out["other"], 1)
            self.assertEqual(len(out["points"]), len(g) + len(new))
            self.assertFalse(any("_forest_pct" in p for p in out["points"]))

    def test_waits_for_listed_zones(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cache"))
            put(os.path.join(d, "zones_extra.json"), {"zones": [{"id": "z1"}, {"id": "z2"}]})
            for y in (2024, 2025):
                put(os.path.join(d, "cache", "arch_z1_%d.json" % y), "{}")
            put(os.path.join(d, "cache", "arch2_z2_2025.json"), "{}")
            old = G.ROOT, G.CACHE, G.SKILL
            G.ROOT, G.CACHE, G.SKILL = d, os.path.join(d, "cache"), os.path.join(d, "noskill")
            try:
                self.assertEqual(G.zones_still_filling([2024, 2025]), ["z2"])
            finally:
                G.ROOT, G.CACHE, G.SKILL = old


if __name__ == "__main__":
    unittest.main()
