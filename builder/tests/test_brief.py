"""The numbers handed to the brief-writing model are already rounded, carry units, and the prompt asks for plain words.
Offline; no key and no network.
    cd /opt/shrooms && python3 -B -W ignore tests/test_brief.py"""
import os
import re
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, "/opt/shrooms")
import shrooms_brief as BR  # noqa: E402


def fixture():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE weather_daily (zone TEXT, date TEXT, source TEXT, rh_mean REAL, vpd_kpa REAL, "
                "soil_m_shallow REAL, soil_t_shallow_f REAL, precip_in REAL)")
    # the long decimals a real run has
    con.execute("INSERT INTO weather_daily VALUES ('a', '2026-11-18', 'forecast', 63.97916666, 0.4486, 0.2843, 44.0369, 0.31)")
    con.execute("INSERT INTO weather_daily VALUES ('b', '2026-11-18', 'forecast', 78.5, 0.2149, 0.3151, 48.4999, 0.0)")
    live = {"zones": {
        "a": {"species": {"chanterelle": {"score": 94, "label": "prime"}}, "forecast": {"rain_10d_in": 1.8497, "daily_high_lowest_f": 42.14, "daily_high_highest_f": 62.6}},
        "b": {"species": {"king_fall": {"score": 80, "label": "good"}}, "forecast": {"rain_10d_in": 0.8412, "daily_high_lowest_f": 44.0, "daily_high_highest_f": 61.5}},
    }}
    zones = [{"id": "a", "name": "Zone A"}, {"id": "b", "name": "Zone B"}]
    return live, zones, con


class Prompt(unittest.TestCase):
    def setUp(self):
        self.prompt, self.rows = BR._digest(*fixture())
        self.lines = [ln for ln in self.prompt.split("\n") if ln.startswith("- ")]

    def test_every_number_is_rounded_before_the_model_sees_it(self):
        self.assertEqual(len(self.lines), 2)
        for ln in self.lines:
            self.assertIsNone(re.search(r"\d+\.\d\d", ln), "two or more decimals reached the prompt: " + ln)
        a = self.lines[0]
        self.assertIn("soil temperature 44 F", a)          # not 44.0
        self.assertIn("humidity 64 percent", a)            # not 63.97916666 or 64.0
        self.assertIn("soil moisture 28 percent", a)       # a fraction in the database, percent in the prompt
        self.assertIn("1.8 inches of rain", a)
        self.assertIn("daily highs 42 to 63 F", a)
        self.assertNotRegex(a, r"\b(temperature|humidity|moisture|highs?) \d+\.0\b")

    def test_whole_numbers_print_without_a_decimal_point(self):
        for v in (44.0, 44.4999, 63.97916666, 0.0):
            self.assertNotIn(".", str(BR._whole(v)))
        self.assertEqual(BR._whole(None), "unknown")
        self.assertEqual(BR._whole(63.5), 64)

    def test_the_date_and_scores_are_still_there(self):
        self.assertRegex(self.prompt, r"Date: \d{4}-\d{2}-\d{2}")
        self.assertIn("score 94 out of 100", self.lines[0])

    def test_the_instructions_ask_for_plain_words_whole_numbers_and_units(self):
        s = BR.SYSTEM.lower()
        for needle in ("plain, everyday words", "never use the word 'likelihood'", "whole numbers", "unit on every number"):
            self.assertIn(needle, s)
        # the old wording that invited the stiff phrasing is gone
        self.assertNotIn("scores are likelihoods", s)

    def test_the_ai_disclaimer_is_kept(self):
        self.assertIn("Written by an AI model", BR.NOTE)
        self.assertIn("It can be wrong", BR.NOTE)


if __name__ == "__main__":
    unittest.main()
