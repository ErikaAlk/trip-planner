#!/usr/bin/env python3
r"""test_tencent_lbs.py — offline checks for tencent_lbs.py.

Pure logic only: no network, no API key needed, safe to run in CI.
The network paths are covered by `tencent_lbs.py selfcheck`.

Run:
    python3 test_tencent_lbs.py
    py       test_tencent_lbs.py      # Windows
"""

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tencent_lbs as T  # noqa: E402


class TestCoordinateConversion(unittest.TestCase):
    """The single most damaging bug this module can have.

    Tencent speaks GCJ-02; the trip-planner map is Leaflet + OSM (WGS-84).
    Skipping the conversion puts every pin ~500 m off — consistently one
    street over, which looks plausible enough to ship.
    """

    # Real GCJ-02 values returned by Tencent's place search.
    GCJ_SAMPLES = [
        (30.663831, 104.053640),   # 宽窄巷子, 成都
        (31.239580, 121.499763),   # 东方明珠, 上海
        (39.908823, 116.397470),   # 天安门, 北京
        (23.129080, 113.264360),   # 广州
    ]

    def test_round_trip_is_stable(self):
        """gcj->wgs->gcj must return to where it started, sub-metre."""
        for lat, lng in self.GCJ_SAMPLES:
            w_lat, w_lng = T.gcj02_to_wgs84(lat, lng)
            back = T.wgs84_to_gcj02(w_lat, w_lng)
            drift = T.haversine_m((lat, lng), back)
            self.assertLess(drift, 1.0,
                            "round-trip drifted {:.2f} m at {},{}".format(drift, lat, lng))

    def test_conversion_actually_moves_the_point(self):
        """A no-op conversion is the failure mode we must never ship.

        If someone 'simplifies' gcj02_to_wgs84 to `return lat, lng`, the
        round-trip test above still passes. This one does not.
        """
        for lat, lng in self.GCJ_SAMPLES:
            shift = T.haversine_m((lat, lng), T.gcj02_to_wgs84(lat, lng))
            self.assertGreater(shift, 100.0,
                               "GCJ-02 offset should be hundreds of metres, got "
                               "{:.1f} m — conversion looks like a no-op".format(shift))
            self.assertLess(shift, 900.0,
                            "offset of {:.1f} m is larger than GCJ-02 ever is".format(shift))

    def test_outside_china_is_untouched(self):
        """GCJ-02 only applies inside China; converting abroad corrupts data."""
        for lat, lng in [(35.6812, 139.7671),      # Tokyo
                         (40.7128, -74.0060),      # New York
                         (-33.8688, 151.2093)]:    # Sydney
            self.assertEqual(T.gcj02_to_wgs84(lat, lng), (lat, lng))
            self.assertEqual(T.wgs84_to_gcj02(lat, lng), (lat, lng))

    def test_known_offset_direction(self):
        """Cross-checked against Tencent's own /ws/coord/v1/translate.

        东方明珠 GCJ (31.239580, 121.499763) resolves to WGS
        (31.241580, 121.495314): the true position is NORTH and WEST of the
        GCJ one. Locks in the sign so an inverted transform is caught.
        """
        w_lat, w_lng = T.gcj02_to_wgs84(31.239580, 121.499763)
        self.assertGreater(w_lat, 31.239580, "WGS latitude should be north of GCJ here")
        self.assertLess(w_lng, 121.499763, "WGS longitude should be west of GCJ here")
        self.assertAlmostEqual(w_lat, 31.241580, places=4)
        self.assertAlmostEqual(w_lng, 121.495314, places=4)

    def test_haversine_against_known_distance(self):
        """One degree of latitude is ~111 km anywhere on the globe."""
        self.assertAlmostEqual(T.haversine_m((30.0, 104.0), (31.0, 104.0)) / 1000,
                               111.2, delta=1.0)


class TestRelevanceScoring(unittest.TestCase):
    """Guards the false-positive trap.

    Tencent's place search returns status=0 with a page of unrelated POIs for
    a nonsense query — it never says "not found". Without this check the skill
    writes a residential compound's coordinates into the itinerary carrying an
    "API-verified" label.
    """

    def test_real_lookups_score_high(self):
        for query, title in [("宽窄巷子", "宽窄巷子"),
                             ("宽窄巷子", "宽窄巷子景区-西门"),
                             ("武侯祠", "武侯祠博物馆"),
                             ("大熊猫基地", "成都大熊猫繁育研究基地"),
                             ("杜甫草堂", "成都杜甫草堂博物馆")]:
            score = T.coverage(query, title)
            self.assertGreaterEqual(score, T._CONF_OK,
                                    "{!r} vs {!r} scored {}".format(query, title, score))
            self.assertEqual(T._confidence(score), "high")

    def test_garbage_lookups_score_zero(self):
        """These are the actual unrelated POIs Tencent returned in testing."""
        for query, title in [("这个地方根本不存在zzzqqq", "富丽碧蔓汀"),
                             ("qwertyuiop", "西河街道"),
                             ("这个地方不存在xyz", "清泉镇")]:
            score = T.coverage(query, title)
            self.assertLess(score, T._CONF_WARN,
                            "{!r} vs {!r} scored {}".format(query, title, score))
            self.assertEqual(T._confidence(score), "none")

    def test_partial_match_lands_in_warn_band(self):
        """Half-matches must be flagged, not silently accepted or rejected."""
        self.assertEqual(T._confidence(T.coverage("东门", "西门大街")), "low")

    def test_empty_query_is_not_a_match(self):
        self.assertEqual(T.coverage("", "任意地点"), 0.0)

    def test_noise_characters_do_not_manufacture_a_match(self):
        """A query made only of stopwords must not score as found."""
        self.assertEqual(T.coverage("市区路", "任意地点"), 0.0)


class TestKeyResolution(unittest.TestCase):
    """The key must never be read from, or written to, the repo."""

    def setUp(self):
        self._saved = os.environ.pop("TENCENT_LBS_KEY", None)
        self._cwd = os.getcwd()
        # Windows refuses to delete the process's own cwd, so the sandbox is
        # torn down manually in tearDown *after* chdir'ing back out.
        self._tmp = tempfile.mkdtemp()
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self._tmp, ignore_errors=True)
        os.environ.pop("TENCENT_LBS_KEY", None)
        if self._saved is not None:
            os.environ["TENCENT_LBS_KEY"] = self._saved

    def _write_key_file(self, body):
        with open(".tencent-lbs-key", "w", encoding="utf-8") as fh:
            fh.write(body)

    def test_explicit_argument_wins(self):
        os.environ["TENCENT_LBS_KEY"] = "FROM-ENV"
        self.assertEqual(T.load_key("FROM-ARG"), "FROM-ARG")

    def test_environment_is_used_when_no_argument(self):
        os.environ["TENCENT_LBS_KEY"] = "FROM-ENV"
        self.assertEqual(T.load_key(), "FROM-ENV")

    def test_file_is_read_and_comments_skipped(self):
        self._write_key_file("# 腾讯位置服务\n\nAAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF\n")
        self.assertEqual(T.load_key(), "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF")

    def test_keyvalue_form_is_accepted(self):
        self._write_key_file('TENCENT_LBS_KEY="AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF"\n')
        self.assertEqual(T.load_key(), "AAAAA-BBBBB-CCCCC-DDDDD-EEEEE-FFFFF")

    def test_missing_key_exits_with_setup_help(self):
        """Must fail loudly with instructions, not fall back to a baked-in key."""
        real_expanduser = T.os.path.expanduser
        T.os.path.expanduser = lambda p: os.path.join(self._tmp, "nohome")
        try:
            with self.assertRaises(SystemExit) as ctx:
                T.load_key()
        finally:
            T.os.path.expanduser = real_expanduser
        message = str(ctx.exception)
        self.assertIn("TENCENT_LBS_KEY", message)
        self.assertIn("lbs.qq.com", message)


class TestNoHardcodedSecret(unittest.TestCase):
    """A key committed to a public repo is the one unrecoverable mistake here."""

    def test_source_carries_no_key_shaped_literal(self):
        import re
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tencent_lbs.py")
        source = open(path, encoding="utf-8").read()
        # Tencent keys look like XXXXX-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX
        pattern = re.compile(r"\b[A-Z0-9]{5}(?:-[A-Z0-9]{5}){5}\b")
        found = [m for m in pattern.findall(source) if not set(m) <= set("AX-")]
        self.assertEqual(found, [], "a real-looking API key is embedded: {}".format(found))


class TestDisplayWidth(unittest.TestCase):
    """The matrix table is unreadable if CJK width is counted as 1."""

    def test_cjk_counts_as_two_cells(self):
        self.assertEqual(T._disp_width("宽窄巷子"), 8)
        self.assertEqual(T._disp_width("abc"), 3)
        self.assertEqual(T._disp_width("成都Aa"), 6)

    def test_clip_respects_cell_budget(self):
        self.assertEqual(T._clip("成都大熊猫繁育研究基地", 10), "成都大熊猫")
        self.assertEqual(T._clip("abcdef", 4), "abcd")

    def test_pad_aligns_by_display_width(self):
        self.assertEqual(T._disp_width(T._pad("宽窄", 10)), 10)
        self.assertEqual(T._disp_width(T._pad("宽窄", 10, right=True)), 10)
        self.assertTrue(T._pad("宽窄", 10, right=True).startswith(" "))


class TestThrottle(unittest.TestCase):
    """5 QPS is a hard ceiling; the matrix endpoint bills per element."""

    def test_calls_are_spaced_out(self):
        throttle = T._Throttle(interval=0.05)
        start = time.monotonic()
        for _ in range(4):
            throttle.wait()
        # 3 gaps of 0.05 s; Windows sleep granularity (~15 ms) means the
        # measured total lands slightly under, so assert on 2.5 gaps not 3.
        self.assertGreaterEqual(time.monotonic() - start, 0.125)

    def test_interval_stays_below_the_quota_ceiling(self):
        """0.2 s == exactly 5 QPS == the ceiling. Must sit strictly under it."""
        self.assertGreater(T._MIN_INTERVAL, 0.2,
                           "interval must leave headroom below the 5 QPS limit")

    def test_matrix_chunk_fits_the_element_budget(self):
        """Measured: 4 elements per request OK, 9 rejected. Never exceed 4."""
        self.assertLessEqual(T._MATRIX_CHUNK, 4)
        self.assertGreaterEqual(T._MATRIX_PAUSE, 1.0)


class TestCityRequirement(unittest.TestCase):
    """`--city` 不是可选的，但只对地名输入而言。

    实测：不带 boundary 直接 348；带 region(中国,0) 返回 status 0 却是空结果。
    两种都对使用者没意义，所以命令入口要拦住并给出可操作提示。
    """

    def test_coordinate_pairs_are_recognised(self):
        """给了坐标就不需要城市，不该被拦下。"""
        for text in ["30.66,104.06", "30.666274,104.051164", "-33.87,151.20", "0,0"]:
            self.assertTrue(T._looks_like_coords(text), text)

    def test_place_names_are_not_coordinates(self):
        for text in ["宽窄巷子", "成都,武侯祠", "30.66", "", "a,b", "30.66,104.06,7"]:
            self.assertFalse(T._looks_like_coords(text), text)

    def test_hint_names_the_missing_flag_and_shows_a_command(self):
        """提示必须能照着做，而不是复述腾讯的报错。"""
        hint = T._NEED_CITY.format("geocode 宽窄巷子")
        self.assertIn("--city", hint)
        self.assertIn("成都", hint)
        self.assertNotIn("348", hint)


class TestErrorHints(unittest.TestCase):
    def test_rate_limit_codes_are_retryable(self):
        self.assertIn(120, T._RATE_LIMITED)
        self.assertIn(121, T._RATE_LIMITED)

    def test_hint_does_not_contradict_tencent_message(self):
        """120's live message says per-second, not daily.

        An earlier version paraphrased it as "当日调用量已达上限", which was
        simply wrong. Hints must add an action, not restate (and mis-state)
        what Tencent already says.
        """
        hint = T._STATUS_HINT[120]
        self.assertNotIn("当日调用量已达上限", hint)

    def test_api_error_surfaces_status_and_message(self):
        err = T.ApiError(190, "无效的key")
        self.assertIn("190", str(err))
        self.assertIn("无效的key", str(err))


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    unittest.main(verbosity=2)
