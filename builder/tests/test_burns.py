"""Offline checks for burns_2027.py (the 2027 Burn Morel Pass teaser layer). No network.
    cd /opt/shrooms && python3 -B tests/test_burns.py
Writes only to a temporary directory."""
import json, math, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, "/opt/shrooms")
import burns_2027 as B  # noqa: E402


def circle(lon, lat, km, n=400):
    """A wobbly closed ring, roughly km in radius, with plenty of points for the simplifier."""
    k = 1 / (111.32 * math.cos(math.radians(lat)))
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        r = km * (1 + 0.03 * math.sin(7 * t))
        pts.append([lon + r * math.cos(t) * k, lat + r * math.sin(t) / 110.54])
    pts.append(pts[0])
    return pts


def feat(name, acres, ring, holes=(), uid="X", start_ms=1752000000000, multi=False):
    rings = [ring] + list(holes)
    geom = {"type": "MultiPolygon", "coordinates": [rings]} if multi else {"type": "Polygon", "coordinates": rings}
    return {"type": "Feature", "geometry": geom, "properties": {
        "poly_IncidentName": name, "poly_GISAcres": acres, "attr_UniqueFireIdentifier": uid,
        "attr_FireDiscoveryDateTime": start_ms, "attr_POOLandownerKind": "Federal"}}


class Geometry(unittest.TestCase):
    def test_simplify_keeps_shape_and_closes(self):
        r = circle(-120.5, 44.3, 8)
        s = B.simplify(r, 0.0008)
        self.assertLess(len(s), len(r) / 2)
        self.assertGreaterEqual(len(s), 4)
        self.assertEqual(s[0], s[-1])
        self.assertAlmostEqual(B.ring_acres(s), B.ring_acres(r), delta=B.ring_acres(r) * 0.05)

    def test_area_is_sane(self):
        # 8 km radius is about 50,000 acres; the wobble adds a little
        a = B.ring_acres(circle(-120.5, 44.3, 8))
        self.assertTrue(45000 < a < 55000, a)

    def test_tiny_hole_dropped_big_hole_kept(self):
        g = {"type": "Polygon", "coordinates": [circle(-120.5, 44.3, 8), circle(-120.5, 44.3, 0.05), circle(-120.45, 44.3, 1.5)]}
        polys = B.clean_polys(g, 0.0008, 40)
        self.assertEqual(len(polys), 1)
        self.assertEqual(len(polys[0]), 2)

    def test_sliver_outer_ring_drops_polygon(self):
        g = {"type": "MultiPolygon", "coordinates": [[circle(-120.5, 44.3, 8)], [circle(-119.0, 44.0, 0.05)]]}
        self.assertEqual(len(B.clean_polys(g, 0.0008, 40)), 1)


class Names(unittest.TestCase):
    def test_tidy(self):
        self.assertEqual(B.tidy_name("FOX"), "Fox")
        self.assertEqual(B.tidy_name("WRIGHTS SPRING"), "Wrights Spring")
        self.assertEqual(B.tidy_name("MCCULLY"), "McCully")
        self.assertEqual(B.tidy_name("BIG GRASS"), "Big Grass")
        self.assertEqual(B.tidy_name("OR-PRD-000123"), "OR-PRD-000123")


class OregonShare(unittest.TestCase):
    # a square "Oregon" from -121 to -119 lon, 43 to 45 lat
    OR = [[[[-121, 43], [-119, 43], [-119, 45], [-121, 45], [-121, 43]]]]

    def test_inside_is_whole(self):
        polys = B.clean_polys({"type": "Polygon", "coordinates": [circle(-120.0, 44.0, 10)]}, 0.0008, 40)
        self.assertEqual(B.oregon_share(polys, self.OR), 1.0)

    def test_straddling_is_about_half(self):
        polys = B.clean_polys({"type": "Polygon", "coordinates": [circle(-119.0, 44.0, 10)]}, 0.0008, 40)
        self.assertAlmostEqual(B.oregon_share(polys, self.OR), 0.5, delta=0.03)

    def test_build_reports_oregon_acres(self):
        f = [feat("BIG GRASS", 100000, circle(-119.0, 44.0, 10), uid="Z")]
        out, _ = B.build(f, 2026, {}, [], {}, oregon=self.OR)
        self.assertEqual(out["fires"][0]["acres"], 100000)
        self.assertTrue(47000 < out["fires"][0]["or_acres"] < 53000, out["fires"][0]["or_acres"])

    def test_real_outline_loads(self):
        path = os.path.join(os.path.dirname(os.path.dirname(HERE)), "site", "oregon.json")
        if not os.path.exists(path):
            self.skipTest("site/oregon.json not next to the builder")
        o = B.load_oregon(path)
        self.assertTrue(B.in_polys(-122.68, 45.52, o))       # Portland
        self.assertFalse(B.in_polys(-116.2, 43.6, o))        # Boise


class Build(unittest.TestCase):
    def setUp(self):
        self.feats = [
            feat("CROSSWHITE", 90000.4, circle(-120.3, 44.4, 12), uid="A"),
            feat("CROSSWHITE", 1200, circle(-120.3, 44.4, 2), uid="A"),          # older, smaller perimeter
            feat("BENCH", 40000, circle(-121.5, 44.8, 8), uid="B"),
            feat("Wrights Spring Fire", 15000, circle(-118.9, 44.9, 6), uid="C", multi=True),
            feat("", 5000, circle(-122.0, 43.0, 4), uid="D"),
        ]
        self.closures = {
            "Crosswhite": {"status": "partial", "order_url": "https://www.fs.usda.gov/ochoco", "checked": "2026-11-18"},
            "Wrights Spring": {"status": "bogus", "order_url": "http://example.invalid/x"},
        }
        self.exclude = [{"name": "Bench Fire", "reason": "tribal land"}]
        self.conifer = {"crosswhite": 61000}

    def test_build(self):
        out, dropped = B.build(self.feats, 2026, self.closures, self.exclude, self.conifer)
        names = [f["name"] for f in out["fires"]]
        self.assertEqual(names, ["Crosswhite", "Wrights Spring Fire"])
        self.assertEqual(dropped, [{"name": "Bench", "reason": "tribal land"}])
        cw = out["fires"][0]
        self.assertEqual(cw["acres"], 90000)                     # largest perimeter wins
        self.assertEqual(cw["conifer_acres"], 61000)
        self.assertEqual(cw["closure"]["status"], "partial")
        self.assertEqual(cw["start"], "2025-07-08")
        ws = out["fires"][1]
        self.assertEqual(ws["closure"]["status"], "unknown")      # bad status is not trusted
        self.assertIsNone(ws["closure"]["order_url"])             # http links are not passed to the page
        self.assertIsNone(ws["conifer_acres"])
        for f in out["fires"]:
            for poly in f["polys"]:
                for ring in poly:
                    self.assertEqual(ring[0], ring[-1])
                    for lon, lat in ring:
                        self.assertTrue(-125 < lon < -116 and 41 < lat < 47)

    def test_cli_fixture_and_conifer_csv(self):
        with tempfile.TemporaryDirectory() as d:
            fx = os.path.join(d, "f.geojson")
            json.dump({"type": "FeatureCollection", "features": self.feats}, open(fx, "w"))
            csvp = os.path.join(d, "conifer.csv")
            open(csvp, "w").write("fire_name,total_acres,conifer_acres,conifer_pct\nCrosswhite,90000,61000.6,68\n")
            out = os.path.join(d, "c", "burns.json")
            os.environ["BURN_PASS_DIR"] = d                       # no side tables there: nothing excluded
            try:
                import importlib
                importlib.reload(B)
                rc = B.main(["--fixture", fx, "--conifer", csvp, "--out", out, "--oregon", os.path.join(d, "none.json")])
            finally:
                os.environ.pop("BURN_PASS_DIR", None)
                importlib.reload(B)
            self.assertEqual(rc, 0)
            data = json.load(open(out))
            self.assertEqual(len(data["fires"]), 3)
            self.assertEqual(data["fires"][0]["conifer_acres"], 61001)
            self.assertIn("or_acres", data["fires"][0])
            self.assertLess(os.path.getsize(out), 60000)

    def test_empty_refuses_to_write(self):
        with tempfile.TemporaryDirectory() as d:
            fx = os.path.join(d, "f.geojson")
            json.dump({"features": []}, open(fx, "w"))
            out = os.path.join(d, "burns.json")
            self.assertEqual(B.main(["--fixture", fx, "--out", out]), 1)
            self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
