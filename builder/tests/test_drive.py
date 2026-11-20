"""Every zone in the build output has a drive time from Portland, so the list shows one comparable number and the
"Distance from Portland" sort uses it. Offline. Run on the server as the others are:
    cd /opt/shrooms && python3 -B -W ignore tests/test_drive.py"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BUILDER = os.path.dirname(HERE)
sys.path.insert(0, BUILDER)
sys.path.insert(0, "/opt/shrooms")
_scout = os.path.join(os.path.dirname(BUILDER), "scout")
if not os.path.isdir(os.environ.get("SHROOMS_SKILL", "/opt/mushroom-scout")) and os.path.isdir(_scout):
    os.environ["SHROOMS_SKILL"] = _scout
if not os.path.isdir(os.environ.get("SHROOMS_ROOT", "/opt/shrooms")):
    os.environ["SHROOMS_ROOT"] = BUILDER  # a repo checkout: the builder folder holds zones_extra.json
import shrooms_build as B  # noqa: E402


class DriveTimes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reg = B.sc.load_registry()
        zones, cls.zx, px = B.all_zones()
        cls.out = B.build_zones(reg, zones, {}, cls.zx, px, series={})

    def test_every_zone_has_a_drive_time(self):
        self.assertGreater(len(self.out), 30)
        for z in self.out:
            self.assertIsInstance(z["pdx_drive_h"], (int, float), z["name"])
            self.assertGreater(z["pdx_drive_h"], 0, z["name"])
            self.assertIn(z["pdx_drive_est"], (True, False), z["name"])

    def test_estimates_are_flagged_and_hand_entered_times_are_kept(self):
        extra = {z["id"]: z for z in self.zx["zones"]}
        for z in self.out:
            hand = extra.get(z["id"], {}).get("pdx_drive_h")
            if hand:
                self.assertEqual((z["pdx_drive_h"], z["pdx_drive_est"]), (float(hand), False), z["name"])
            else:
                self.assertTrue(z["pdx_drive_est"], z["name"] + ": an estimated time must be flagged")
                self.assertEqual((z["pdx_drive_h"] * 4) % 1, 0, z["name"] + ": quarter hours")

    def test_a_zone_with_no_road_miles_falls_back_to_straight_line(self):
        z = {"id": "nowhere", "lat": 44.0, "lon": -121.0}
        hours, est = B.drive_time(z, {}, {"drive_avg_mph": 55})
        self.assertTrue(est and hours > 1)

    def test_every_road_mile_entry_names_a_real_zone(self):
        ids = {z["id"] for z in self.out}
        self.assertTrue(set(self.zx["drive_road_miles"]) <= ids)

    def test_farther_by_road_is_not_shorter(self):
        # a sanity check on the estimates: the south coast and Illinois Valley are farther than McKenzie Bridge
        t = {z["id"]: z["pdx_drive_h"] for z in self.out}
        self.assertLess(t["mckenzie_west"], t["illinois_valley"])
        self.assertLess(t["mckenzie_west"], t["south_coast"])
        self.assertLess(t["santiam_pass"], t["chemult_walker"])

    # ---- the "driving from" picker: times from the other starting cities
    def test_every_zone_has_a_time_from_every_city(self):
        ids = [o["id"] for o in self.zx["drive_from"]["origins"]]
        self.assertEqual(ids[0], "portland")
        self.assertEqual(len(ids), 7)
        for z in self.out:
            self.assertEqual(set(z["drives"]), set(ids), z["name"])
            for city, h in z["drives"].items():
                self.assertGreaterEqual(h, 0.25, z["name"] + " from " + city)
                self.assertEqual((h * 4) % 1, 0, z["name"] + " from " + city + ": quarter hours")

    def test_portland_in_the_table_matches_the_portland_fields(self):
        for z in self.out:
            self.assertEqual(z["drives"]["portland"], z["pdx_drive_h"], z["name"])

    def test_city_times_make_geographic_sense(self):
        t = {z["id"]: z["drives"] for z in self.out}
        self.assertLess(t["metolius_greenridge"]["bend"], t["metolius_greenridge"]["portland"])
        self.assertLess(t["cottage_grove_row_river"]["eugene"], 1)
        self.assertLess(t["coos_bay_coast"]["coosbay"], 0.5)
        self.assertLess(t["ashland_applegate"]["medford"], 0.75)
        self.assertLess(t["anthony_elkhorns"]["lagrande"], t["anthony_elkhorns"]["portland"])
        self.assertLess(t["ochoco_mitchell"]["johnday"], t["ochoco_mitchell"]["bend"] + 1)
        self.assertGreater(t["wallowa_joseph"]["coosbay"], 7)

    def test_road_mile_entries_name_real_zones_and_cities(self):
        ids = {z["id"] for z in self.out}
        cities = {o["id"] for o in self.zx["drive_from"]["origins"]}
        for city, row in self.zx["drive_from"]["road_miles"].items():
            self.assertIn(city, cities)
            self.assertTrue(set(row) <= ids, city)

    def test_a_zone_with_no_road_miles_falls_back_to_straight_line_from_each_city(self):
        z = {"id": "nowhere", "lat": 44.0, "lon": -121.0}
        t = B.drive_times_from_cities(z, {}, self.zx)
        self.assertEqual(len(t), 7)
        self.assertLess(t["bend"], t["coosbay"])

    def test_the_pages_menu_lists_the_same_cities(self):
        import re
        site = os.path.join(BUILDER, "site")                    # the server keeps the site under /opt/shrooms
        if not os.path.isdir(site):
            site = os.path.join(os.path.dirname(BUILDER), "site")   # a repo checkout keeps it beside builder/
        js = open(os.path.join(site, "app.js"), encoding="utf-8").read()
        block = re.search(r"const ORIGINS = \[(.*?)\];", js, re.S).group(1)
        page = re.findall(r"\['([a-z]+)',\s*'([^']+)'\]", block)
        want = [(o["id"], o["name"]) for o in self.zx["drive_from"]["origins"]]
        self.assertEqual(page, want)

    def test_compact_table_column_round_trips(self):
        z = self.out[0]
        col = ",".join("%s:%s" % (k, v) for k, v in z["drives"].items())
        back = {k: float(v) for k, v in (p.split(":") for p in col.split(","))}
        self.assertEqual(back, {k: float(v) for k, v in z["drives"].items()})


if __name__ == "__main__":
    unittest.main()
