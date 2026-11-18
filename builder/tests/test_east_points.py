"""Checks for the east-side scoring zones (added 2026-11-18 to cover the big 2026 conifer burns). No network.
    cd /opt/shrooms && python3 -B tests/test_east_points.py            offline checks, plus burn coverage when burns.json exists
    cd /opt/shrooms && python3 -B tests/test_east_points.py --report   also prints every 2026 conifer burn and its nearest zone
Reads only; writes nothing."""
import json, math, os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.dirname(HERE)
sys.path.insert(0, BUILDER)
sys.path.insert(0, "/opt/shrooms")
import burns_2027 as B  # noqa: E402

REPORT = "--report" in sys.argv
if REPORT:
    sys.argv.remove("--report")

EAST_IDS = ["dufur_badger", "ashwood_crooked_grassland", "fossil_kinzua", "ochoco_mitchell", "umatilla_tollgate",
            "anthony_elkhorns", "wallowa_joseph", "malheur_emigrant", "sprague_river_bly"]
MUST_COVER = ["Crosswhite", "Grasshopper", "Hagen", "Wrights Spring", "Shingle"]   # the five biggest 2026 conifer burns
COVER_KM = 40                                                                      # same radius the zone sighting counts use


def read(path):
    with open(path) as fh:
        return fh.read()


def first(*paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


REPO = os.path.dirname(BUILDER)
SKILL = os.environ.get("SHROOMS_SKILL", "/opt/mushroom-scout")
SITE_DATA = os.environ.get("SHROOMS_SITE_DATA", "/opt/shrooms/site/data")
ZX = first(os.path.join(BUILDER, "zones_extra.json"))
PX = first(os.path.join(BUILDER, "permits_extra.json"))
SKILL_ZONES = first(os.path.join(REPO, "scout", "references", "zones.json"), os.path.join(SKILL, "references", "zones.json"))
SKILL_SCRIPTS = first(os.path.join(REPO, "scout", "scripts"), os.path.join(SKILL, "scripts"))
REGISTRY = first(os.path.join(REPO, "scout", "references", "species_registry.json"), os.path.join(SKILL, "references", "species_registry.json"))
OREGON = first(os.path.join(REPO, "site", "oregon.json"), os.path.join(BUILDER, "site", "oregon.json"))
INDEX = first(os.path.join(REPO, "site", "index.html"), os.path.join(BUILDER, "site", "index.html"))
BURNS = first(os.path.join(SITE_DATA, "c", "burns.json"), os.path.join(REPO, "site", "data", "c", "burns.json"))


def hav(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def km_to_burn(lat, lon, polys):
    """0 inside the outline, otherwise the distance to the nearest outline vertex (vertices are ~100 m apart after simplify)."""
    if B.in_polys(lon, lat, polys):
        return 0.0
    return min(hav(lat, lon, y, x) for poly in polys for ring in poly for x, y in ring)


def outline_center(polys):
    pts = [(x, y) for poly in polys for x, y in poly[0]]
    return sum(y for _, y in pts) / len(pts), sum(x for x, _ in pts) / len(pts)


ZXD = json.loads(read(ZX))
ALL = json.loads(read(SKILL_ZONES))["zones"] + ZXD["zones"]
EAST = [z for z in ZXD["zones"] if z["id"] in EAST_IDS]


class Zones(unittest.TestCase):
    def test_all_nine_present_and_ids_unique(self):
        self.assertEqual(sorted(z["id"] for z in EAST), sorted(EAST_IDS))
        ids = [z["id"] for z in ALL]
        self.assertEqual(len(ids), len(set(ids)))

    def test_fields(self):
        regions = set(ZXD["regions"])
        self.assertIn("east", regions)
        for z in EAST:
            for k in ("name", "lat", "lon", "elev_ft", "land", "side", "species", "habitat", "pdx_drive_h", "regions"):
                self.assertIn(k, z, z["id"])
            self.assertEqual(z["side"], "east", z["id"])
            self.assertFalse(z["coastal"], z["id"])
            self.assertTrue(set(z["regions"]) <= regions, z["id"])
            self.assertIn("morel_natural", z["species"], z["id"])
            self.assertTrue(all(ord(c) < 128 for c in json.dumps(z)), z["id"])

    def test_inside_oregon(self):
        if not OREGON:
            self.skipTest("oregon.json not found")
        o = B.load_oregon(OREGON)
        for z in EAST:
            self.assertTrue(B.in_polys(z["lon"], z["lat"], o), z["id"])

    def test_not_stacked_on_an_old_zone(self):
        for z in EAST:
            for o in ALL:
                if o["id"] != z["id"]:
                    self.assertGreater(hav(z["lat"], z["lon"], o["lat"], o["lon"]), 20, (z["id"], o["id"]))

    def test_model_can_score_them(self):
        """Each zone must fall inside the morel elevation band for at least one month, and inside the spring king band."""
        reg = json.loads(read(REGISTRY))["species"]
        bands = reg["morel_natural"]["elev_bands_ft"]
        kb = reg["king_spring"]["elev_bands_ft"]["all"]
        for z in EAST:
            months = [m for m, (lo, hi) in bands.items() if lo <= z["elev_ft"] <= hi]
            self.assertTrue(months, z["id"])
            self.assertTrue(kb[0] <= z["elev_ft"] <= kb[1], z["id"])
            self.assertIn(z["side"], reg["king_spring"]["side_allow"])


class Wiring(unittest.TestCase):
    def test_skill_boxes_cover_every_zone(self):
        """SNOTEL melt-out, the burn join and place lookups used to stop at 44.8 N and 120.6 W."""
        import ast
        for name in ("snotel.py", "fires.py", "geo.py"):
            src = read(os.path.join(SKILL_SCRIPTS, name))
            line = next(l for l in src.splitlines() if l.startswith("BBOX = "))
            box = ast.literal_eval(line.split("=", 1)[1].split("#")[0].strip())
            for z in ALL:
                self.assertTrue(box["min_lat"] <= z["lat"] <= box["max_lat"] and box["min_lon"] <= z["lon"] <= box["max_lon"], (name, z["id"]))

    def test_snotel_rediscovers_after_box_change(self):
        src = read(os.path.join(SKILL_SCRIPTS, "snotel.py"))
        self.assertIn("cache.get('bbox') == BBOX", src)

    def test_every_forest_has_permit_text(self):
        names = [m for e in json.loads(read(PX))["entries"] for m in e["match"]]
        for nf in ("Ochoco NF", "Umatilla NF", "Malheur NF", "Wallowa-Whitman NF"):
            self.assertIn(nf, names)
            self.assertTrue(any(nf in z["land"] for z in EAST), nf)

    def test_filters_offer_the_new_forests_and_region(self):
        if not INDEX:
            self.skipTest("index.html not found")
        html = read(INDEX)
        self.assertIn('<option value="east">', html)
        for z in EAST:
            nf = z["land"].split(" (")[0]
            self.assertIn('<option value="%s">' % nf, html, z["id"])


class Coverage(unittest.TestCase):
    """Uses the live burns layer (site/data/c/burns.json) when it is there; skipped otherwise."""

    def setUp(self):
        if not BURNS:
            self.skipTest("burns.json not found (runs on the server)")
        self.fires = json.loads(read(BURNS))["fires"]

    def nearest(self, f):
        return min(((km_to_burn(z["lat"], z["lon"], f["polys"]), z["id"]) for z in ALL), key=lambda t: t[0])

    def test_big_conifer_burns_have_a_zone(self):
        byname = {f["name"]: f for f in self.fires}
        for name in MUST_COVER:
            self.assertIn(name, byname)
            d, zid = self.nearest(byname[name])
            self.assertLessEqual(d, COVER_KM, "%s: nearest zone %s is %.0f km away" % (name, zid, d))

    def test_report(self):
        if not REPORT:
            return
        rows = sorted((f for f in self.fires if (f.get("conifer_acres") or 0) >= 1000), key=lambda f: -f["conifer_acres"])
        print("\n%-22s %9s %9s  %-9s %-28s %s" % ("burn", "conifer", "OR acres", "center", "nearest zone", "km"))
        for f in rows:
            d, zid = self.nearest(f)
            la, lo = outline_center(f["polys"])
            print("%-22s %9d %9d  %.2f,%.2f %-28s %.0f%s" % (f["name"][:22], f["conifer_acres"], f.get("or_acres") or 0, la, lo,
                                                            zid, d, "" if d <= COVER_KM else "  <- not covered"))


if __name__ == "__main__":
    unittest.main()
