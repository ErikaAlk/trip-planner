#!/usr/bin/env python3
r"""test_exa_facts.py — offline checks for exa_facts.py.

Pure logic: no network, no API key, no spend. The network paths are covered by
`exa_facts.py selfcheck` (which does cost about $0.008).

Run:
    python3 test_exa_facts.py
    py       test_exa_facts.py      # Windows
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import exa_facts as E  # noqa: E402


# Real text captured from https://www.panda.org.cn/cn/service/ticket/ — the
# navigation wall really does precede the facts, and really does contain the
# words we search for.
NAV_NOISE = ("票务服务 - 成都大熊猫繁育研究基地 首页 虚拟景区 基地动态 熊猫趣闻 焦点活动 "
             "单位公告 科普辟谣 游客服务 开放时间 票务服务 观光车服务 讲解服务 导览地图 "
             "餐饮、购物 公共交通 游客须知 医疗服务 失物招领 联系我们 科研保护 学术交流")

REAL_FACTS = ("票务服务 1、全线上实名预约： 景区最大限流人数为8.5万人次/日，所有游客均须"
              "线上实名预约。 2、开放时间： 每年11月至次年2月——上午票入园时间：8:00-12:00；"
              "下午票入园时间：12:00-16:30；17:30开始清园。 3、预订时间： 可线上提前14日预订门票。")


class TestFactWindows(unittest.TestCase):
    """The reason this function exists: official pages bury facts under menus."""

    def test_navigation_only_text_is_rejected(self):
        """A menu matches the keywords but carries no number — must be dropped.

        Without the digit test, `verify` wasted a whole window printing the
        site's navigation tree. Measured on the real page.
        """
        self.assertIsNone(E.fact_windows(NAV_NOISE))

    def test_real_fact_passage_is_kept(self):
        windows = E.fact_windows(REAL_FACTS)
        self.assertTrue(windows)
        joined = " ".join(windows)
        for token in ("8.5万", "8:00-12:00", "提前14日"):
            self.assertIn(token, joined, "丢了关键事实: " + token)

    def test_menu_before_facts_does_not_swallow_the_facts(self):
        """The realistic case: nav wall, then the facts. Facts must survive."""
        windows = E.fact_windows(NAV_NOISE + " " + REAL_FACTS)
        self.assertTrue(windows)
        self.assertIn("8.5万", " ".join(windows))

    def test_no_keyword_match_returns_none(self):
        """None means 'nothing matched', so the caller shows the plain prefix
        instead of silently hiding the page."""
        self.assertIsNone(E.fact_windows("这是一段完全无关的文字，讲的是别的事情 2026"))

    def test_empty_input_is_safe(self):
        self.assertIsNone(E.fact_windows(""))
        self.assertIsNone(E.fact_windows(None))

    def test_window_is_capped(self):
        """A fact-dense page merges into one span; it must not return the whole
        document."""
        dense = " ".join(["开放时间 8:00 门票 55元 预约 限流 1000人"] * 200)
        for w in E.fact_windows(dense):
            self.assertLessEqual(len(w), E._MAX_WINDOW + 40)

    def test_limit_is_respected(self):
        spread = " 无关内容 " * 30
        text = spread.join(["开放时间 8:0{}".format(i) for i in range(9)])
        self.assertLessEqual(len(E.fact_windows(text, limit=3)), 3)


class TestSourceRanking(unittest.TestCase):
    """Official pages must outrank aggregators — aggregators go stale."""

    def test_official_hosts_rank_first(self):
        for url in ["https://www.panda.org.cn/cn/service/ticket/",
                    "https://mm.gov.cn/notice",
                    "https://m.panda.org.cn/cn/service/opentime/"]:
            self.assertEqual(E._rank(url), 0, url)
            self.assertEqual(E._source_kind(url), "官方")

    def test_aggregators_rank_last(self):
        for url in ["https://cd.bendibao.com/jingdian/x.html",
                    "https://www.mafengwo.cn/poi/1.html",
                    "https://www.dianping.com/shop/2",
                    "https://gs.ctrip.com/a.html"]:
            self.assertEqual(E._rank(url), 2, url)
            self.assertEqual(E._source_kind(url), "聚合站")

    def test_unknown_hosts_sit_between(self):
        self.assertEqual(E._rank("https://example.com/a"), 1)
        self.assertEqual(E._source_kind("https://example.com/a"), "其它")

    def test_ordering_puts_official_above_aggregator(self):
        urls = ["https://cd.bendibao.com/x", "https://example.com/y",
                "https://www.panda.org.cn/z"]
        self.assertEqual(sorted(urls, key=E._rank)[0], "https://www.panda.org.cn/z")

    def test_malformed_url_does_not_crash(self):
        for bad in ["", "not a url", "http://"]:
            E._rank(bad)
            E._source_kind(bad)


class TestBudget(unittest.TestCase):
    """Exa bills per call. A runaway batch must stop, not surprise the user."""

    def test_spend_accumulates_reported_cost(self):
        s = E.Spend()
        s.add("/search", 0.007)
        s.add("/contents", 0.001)
        self.assertAlmostEqual(s.total, 0.008)
        self.assertEqual(s.calls, 2)

    def test_falls_back_to_measured_price_when_api_reports_none(self):
        s = E.Spend()
        s.add("/search", None)
        self.assertAlmostEqual(s.total, E._PRICE["/search"])

    def test_budget_blocks_the_call_before_it_is_made(self):
        s = E.Spend(budget=0.010)
        s.check("/search")
        s.add("/search", 0.007)
        s.check("/contents")
        s.add("/contents", 0.001)
        # 0.008 spent; another search would reach 0.015 > 0.010
        with self.assertRaises(E.BudgetExceeded):
            s.check("/search")

    def test_no_budget_means_no_ceiling(self):
        s = E.Spend()
        for _ in range(50):
            s.check("/search")
            s.add("/search", 0.007)
        self.assertGreater(s.total, 0.3)

    def test_budget_message_names_the_flag(self):
        s = E.Spend(budget=0.001)
        with self.assertRaises(E.BudgetExceeded) as ctx:
            s.check("/search")
        self.assertIn("--budget", str(ctx.exception))


class TestKeyResolution(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("EXA_API_KEY", None)
        self._cwd = os.getcwd()
        self._tmp = tempfile.mkdtemp()
        os.chdir(self._tmp)

    def tearDown(self):
        os.chdir(self._cwd)
        shutil.rmtree(self._tmp, ignore_errors=True)
        os.environ.pop("EXA_API_KEY", None)
        if self._saved is not None:
            os.environ["EXA_API_KEY"] = self._saved

    def test_explicit_argument_wins(self):
        os.environ["EXA_API_KEY"] = "FROM-ENV"
        self.assertEqual(E.load_key("FROM-ARG"), "FROM-ARG")

    def test_environment_is_used(self):
        os.environ["EXA_API_KEY"] = "FROM-ENV"
        self.assertEqual(E.load_key(), "FROM-ENV")

    def test_file_is_read_and_comments_skipped(self):
        with open(".exa-key", "w", encoding="utf-8") as fh:
            fh.write("# exa\n\n00000000-1111-2222-3333-444444444444\n")
        self.assertEqual(E.load_key(), "00000000-1111-2222-3333-444444444444")

    def test_missing_key_exits_with_setup_help_and_cost_warning(self):
        real = E.os.path.expanduser
        E.os.path.expanduser = lambda p: os.path.join(self._tmp, "nohome")
        try:
            with self.assertRaises(SystemExit) as ctx:
                E.load_key()
        finally:
            E.os.path.expanduser = real
        msg = str(ctx.exception)
        self.assertIn("EXA_API_KEY", msg)
        self.assertIn("dashboard.exa.ai", msg)
        # Costing money is the thing a new user most needs told up front.
        self.assertIn("计费", msg)


class TestNoHardcodedSecret(unittest.TestCase):
    def test_source_carries_no_uuid_shaped_literal(self):
        import re
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exa_facts.py")
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        pattern = re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
        # Placeholder UUIDs in docs and tests are built from one or two repeated
        # digits (00000000-1111-2222-…); a real key has many distinct ones.
        found = [m for m in pattern.findall(source)
                 if len(set(m.replace("-", ""))) > 3]
        self.assertEqual(found, [], "源码里有真实形状的 Key: {}".format(found))


class TestDocumentedCommandsParse(unittest.TestCase):
    """The docstring's examples must actually run.

    An earlier version put --key/--json on the top level only, so the exact
    command written in SKILL.md (`geocode --file x --city 成都 --json`) failed
    with 'unrecognized arguments'. Docs that don't parse are worse than no docs.
    """

    def _parse(self, argv):
        return E.build_parser().parse_args(argv)

    def test_options_after_subcommand(self):
        args = self._parse(["verify", "宽窄巷子", "--city", "成都", "--json",
                            "--budget", "0.05"])
        self.assertTrue(args.json)
        self.assertAlmostEqual(args.budget, 0.05)

    def test_every_subcommand_accepts_the_shared_options(self):
        for argv in (["verify", "x", "--json"],
                     ["fetch", "https://example.com", "--json"],
                     ["search", "q", "--json"],
                     ["answer", "q", "--json"],
                     ["selfcheck", "--json"]):
            self.assertTrue(self._parse(argv).json, argv)

    def test_budget_accepted_on_every_subcommand(self):
        for argv in (["verify", "x"], ["fetch", "u"], ["search", "q"],
                     ["answer", "q"], ["selfcheck"]):
            self.assertAlmostEqual(self._parse(argv + ["--budget", "1.5"]).budget, 1.5)

    def test_site_filter_takes_multiple_domains(self):
        args = self._parse(["search", "成都 酒店", "--site",
                            "xiaohongshu.com", "dianping.com"])
        self.assertEqual(args.site, ["xiaohongshu.com", "dianping.com"])


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    unittest.main(verbosity=2)
