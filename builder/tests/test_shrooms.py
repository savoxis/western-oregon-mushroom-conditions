"""Self-contained checks for the shrooms builder helpers. Run on the VPS as user mushroom:
    cd /opt/shrooms && python3 -B tests/test_shrooms.py           (unit checks only, no network)
    cd /opt/shrooms && python3 -B tests/test_shrooms.py --live    (adds one live check: forecast day 0 equals the live score)
Production files are never written: temporary directories are used for anything that writes."""
import io, json, os, sys, tempfile, unittest, urllib.error, urllib.request

sys.path.insert(0, "/opt/shrooms")
LIVE = "--live" in sys.argv
if LIVE:
    sys.argv.remove("--live")


class OmKey(unittest.TestCase):
    def setUp(self):
        import om_key
        self.k = om_key
        om_key._cache.clear()
        os.environ["OPENMETEO_API_KEY"] = "TESTKEY123"
        os.environ["OPENMETEO_ARCHIVE_CUSTOMER"] = "0"

    def tearDown(self):
        self.k._cache.clear()
        os.environ.pop("OPENMETEO_API_KEY", None)
        os.environ.pop("OPENMETEO_ARCHIVE_CUSTOMER", None)

    def test_forecast_rewritten(self):
        u = self.k.rewrite("https://api.open-meteo.com/v1/forecast?latitude=1&longitude=2")
        self.assertTrue(u.startswith("https://customer-api.open-meteo.com/v1/forecast?latitude=1&longitude=2&apikey="))

    def test_archive_left_alone_without_flag(self):
        u = "https://archive-api.open-meteo.com/v1/archive?latitude=1"
        self.assertEqual(self.k.rewrite(u), u)

    def test_archive_rewritten_with_flag(self):
        os.environ["OPENMETEO_ARCHIVE_CUSTOMER"] = "1"
        self.k._cache.clear()
        self.assertIn("customer-archive-api.open-meteo.com", self.k.rewrite("https://archive-api.open-meteo.com/v1/archive?x=1"))

    def test_other_hosts_untouched(self):
        for u in ("https://api.gbif.org/v1/occurrence/1", "https://geocoding-api.open-meteo.com/v1/search?name=x", "https://evil.example/api.open-meteo.com"):
            self.assertEqual(self.k.rewrite(u), u)

    def test_no_double_key(self):
        u = "https://api.open-meteo.com/v1/forecast?apikey=abc"
        self.assertEqual(self.k.rewrite(u), u)

    def test_fallback_to_free_host_on_plan_error(self):
        seen = []

        def fake(req, *a, **kw):
            url = req.full_url if hasattr(req, "full_url") else req
            seen.append(url)
            if "customer-" in url:
                raise urllib.error.HTTPError(url, 403, "plan", {}, io.BytesIO(b"{}"))
            return "ok"
        old = sys.stderr
        sys.stderr = io.StringIO()
        try:
            r = self.k.urlopen(urllib.request.Request("https://api.open-meteo.com/v1/forecast?a=1"), _orig=fake)
        finally:
            msg = sys.stderr.getvalue()
            sys.stderr = old
        self.assertEqual(r, "ok")
        self.assertEqual(len(seen), 2)
        self.assertNotIn("apikey", seen[1])
        self.assertNotIn("TESTKEY123", msg)          # the warning never contains the key

    def test_server_errors_are_not_masked(self):
        def fake(req, *a, **kw):
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, io.BytesIO(b""))
        with self.assertRaises(urllib.error.HTTPError):
            self.k.urlopen(urllib.request.Request("https://api.open-meteo.com/v1/forecast?a=1"), _orig=fake)


class Builder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import shrooms_build as b
        cls.b = b

    def test_features_at(self):
        dates = ["2026-10-%02d" % d for d in range(1, 31)]
        precip = [0.0] * 30
        precip[20] = 0.6
        precip[27] = 0.2
        tmin = [40.0] * 30
        tmin[29] = 27.0
        tmax = [60.0] * 30
        soil = [50.0] * 30
        f = self.b.features_at(29, dates, precip, tmin, tmax, soil, [0.3] * 30)
        self.assertAlmostEqual(f["precip_7d"], 0.2)
        self.assertAlmostEqual(f["precip_14d"], 0.8)
        self.assertEqual(f["frost_nights_last3"], 1)
        self.assertEqual(f["last_rain_event"], "2026-10-28")
        self.assertAlmostEqual(f["soil_t_7d_mean"], 50.0)

    def test_archive_ok(self):
        b = self.b
        real = b.om_key.urlopen
        try:
            def q429(*a, **kw):
                raise urllib.error.HTTPError("u", 429, "lim", {}, io.BytesIO(b'{"reason":"Daily API request limit exceeded."}'))
            b.om_key.urlopen = q429
            ok, why = b.archive_ok()
            self.assertFalse(ok)
            self.assertIn("Daily", why)

            def neterr(*a, **kw):
                raise urllib.error.URLError("down")
            b.om_key.urlopen = neterr
            self.assertTrue(b.archive_ok()[0])          # network trouble does not block the nightly
        finally:
            b.om_key.urlopen = real

    def test_fill_daily_cap(self):
        b = self.b
        old_root, old_cache, old_fetch = b.ROOT, b.CACHE, b.fetch_year
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(d + "/data")
            os.makedirs(d + "/cache")
            b.ROOT, b.CACHE = d, d + "/cache"
            calls = []

            def fake_fetch(p, y, net=False, full=False):
                calls.append((p["id"], y, full))
                return {"daily": {}}
            b.fetch_year = fake_fetch
            try:
                pts = [{"id": "z%d" % i, "lat": 44.0, "lon": -122.0, "elev_ft": 1000, "lite": True} for i in range(60)]
                from datetime import datetime
                json.dump({"day": datetime.utcnow().strftime("%F"), "spent": 4400}, open(d + "/data/fill_spend.json", "w"))
                b.run_fill(pts, [2024, 2025], None, 5)
                self.assertLessEqual(len(calls), 5)          # 4,400 already spent: only a few 26-call files fit under 4,500
                led = json.load(open(d + "/data/fill_spend.json"))
                self.assertLessEqual(led["spent"], 4500 + 26)
            finally:
                b.ROOT, b.CACHE, b.fetch_year = old_root, old_cache, old_fetch

    def test_merged_inputs_and_season_rain(self):
        import sqlite3
        b = self.b
        dates = ["2026-10-%02d" % d for d in range(9, 32)] + ["2026-11-%02d" % d for d in range(1, 19)]      # 41 days
        ent = {"data": {"daily": {"time": dates, "precipitation_sum": [0.0] * 41, "temperature_2m_min": [40.0] * 41,
                                  "temperature_2m_max": [60.0] * 41},
                        "hourly": {"time": [d + "T12:00" for d in dates], "soil_temperature_6cm": [50.0] * 41,
                                   "soil_moisture_3_to_9cm": [0.3] * 41}}}
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE weather_daily (zone TEXT, date TEXT, source TEXT, precip_in REAL)")
        for d in ["2026-10-25", "2026-10-26"]:
            con.execute("INSERT INTO weather_daily VALUES ('zz', ?, 'era5', 0.7)", (d,))
        con.execute("INSERT INTO weather_daily VALUES ('zz', '2026-11-15', 'era5', 9.9)")      # after "today": must be ignored
        con.execute("INSERT INTO weather_daily VALUES ('zz', '2026-10-27', 'forecast', 5.0)")  # not ERA5: must be ignored
        d0 = b.date(2026, 8, 1)
        while d0 <= b.date(2026, 10, 24):
            con.execute("INSERT INTO weather_daily VALUES ('zz', ?, 'era5', 0.0)", (d0.isoformat(),))
            d0 += b.timedelta(days=1)
        real = b._fc_entry
        b._fc_entry = lambda z: ent
        try:
            mi = b.merged_inputs({"id": "zz", "lat": 0, "lon": 0}, con)
            self.assertEqual(mi["base"], 30)
            self.assertEqual(mi["dates"][30], "2026-11-08")
            self.assertEqual(mi["era5_last"], "2026-10-26")
            self.assertAlmostEqual(sum(mi["precip"][:31]), 1.4)
            self.assertEqual(mi["precip"][dates.index("2026-11-15")], 0.0)
            f = b.features_at(mi["base"], mi["dates"], mi["precip"], mi["tmin"], mi["tmax"], mi["soil_t"], mi["soil_m"])
            self.assertAlmostEqual(f["precip_14d"], 0.7)          # Oct 26 is inside the 14 days ending Nov 8, Oct 25 is not
            self.assertAlmostEqual(f["precip_30d"], 1.4)
            self.assertEqual(f["last_rain_event"], "2026-10-26")
            sr = b.season_rain({"id": "zz"}, con, mi)
            self.assertEqual(sr["daily"]["time"][0], "2026-08-01")
            self.assertEqual(sr["daily"]["time"][-1], "2026-11-08")
            self.assertAlmostEqual(sum(sr["daily"]["precipitation_sum"]), 1.4)
            self.assertIsNone(b.merged_inputs({"id": "zz", "lat": 0, "lon": 0}, None)["era5_last"])
        finally:
            b._fc_entry = real

    @unittest.skipUnless(LIVE, "needs --live (network)")
    def test_forecast_day0_matches_live(self):
        b = self.b
        reg = b.sc.load_registry()
        zones, zx, px = b.all_zones()
        month = b.datetime.now(b.TZ).month
        checked = 0
        for z in zones:
            sp = [k for k in b.zone_species(reg, z) if b.species_in_window(reg, k, z, month)]
            if not sp:
                continue
            w = b.run_json("weather.py", z["lat"], z["lon"], month)
            if not w or "error" in w:
                continue
            import sqlite3
            con = sqlite3.connect("file:/opt/shrooms/data/live_history.sqlite?mode=ro", uri=True)
            mi = b.merged_inputs(z, con)
            if mi:
                f0 = b.features_at(mi["base"], mi["dates"], mi["precip"], mi["tmin"], mi["tmax"], mi["soil_t"], mi["soil_m"])
                for fk in ("precip_7d", "precip_14d", "precip_30d", "last_rain_event"):
                    w[fk] = f0[fk]
                if month >= 8:
                    ad = b.season_rain(z, con, mi)
                    if ad:
                        w["archive_data"] = ad
            live = {}
            for k in sp:
                r = b.sc.score_species(b.reg_for(reg, z), k, z, month, w)
                if r["label"] != "gated out":
                    live[k] = r["score"]
            fc = b.forecast_scores(reg, z, list(live), w, month, con=con)
            for k, arr in fc.items():
                self.assertEqual(arr[0], live[k], "%s %s" % (z["id"], k))
                self.assertTrue(all(v is None or 0 <= v <= 100 for v in arr))
                checked += 1
            if checked >= 6:
                break
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
