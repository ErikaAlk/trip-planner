#!/usr/bin/env python3
r"""exa_facts.py — Exa search/fetch for trip-planner's hardest data class.

Targets the row of the data-integrity contract that has always been a hedge:
门票 / 营业时间 / 预约配额 / 官方公告. Those live on official pages that are
tedious to find by hand, and `web_search` alone returns summaries rather than
the page text you need to quote.

Usage:
    python3 exa_facts.py selfcheck
    python3 exa_facts.py verify 成都大熊猫繁育研究基地 --city 成都
    python3 exa_facts.py verify --file stops.txt --city 成都 --json
    python3 exa_facts.py fetch https://m.panda.org.cn/cn/service/opentime/
    python3 exa_facts.py search "成都 亲子 景点" --site xiaohongshu.com
    py       exa_facts.py ...                                     # Windows

API key resolution (first hit wins) — never stored in this repo:
    1. --key
    2. $EXA_API_KEY
    3. ./.exa-key                    (cwd, overrides the user default)
    4. ~/.claude/.exa-key
Run `selfcheck` for setup instructions if none is found.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not summarise. `verify` returns the official page's own text plus its
URL, and you read it. Exa also offers `/answer`, which returns a fluent LLM
answer with citations — that is a *discovery* aid, not a source. Writing its
prose into an itinerary as 实查 would be laundering a model's summary into a
verified fact, which is exactly what the contract forbids. Use `--answer` to
locate candidate pages, then read what `fetch` returns from those pages.

COSTS MONEY. Measured against the live API:
    /search            $0.007 per call
    /contents          $0.001 per URL      <- cheap; prefer it
    /answer            $0.005 per call
`verify` spends one search plus one contents per stop (~$0.008). Every command
prints what it spent, and `--budget` stops the run before it exceeds a cap.

CHINESE QUERIES: use this REST path, not the anonymous MCP endpoint. Measured:
the same Chinese query that returns the official page here came back as an
unrelated Wikipedia phonetics article through `mcp.exa.ai` without auth, while
the English query worked on both. Anonymous MCP silently degrades on Chinese.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

BASE = "https://api.exa.ai"
_UA = {"User-Agent": "trip-planner-skill/1.0 (+https://github.com/ErikaAlk/trip-planner)"}

# Measured per-call prices, used for the budget guard and the cost line.
_PRICE = {"/search": 0.007, "/contents": 0.001, "/answer": 0.005}

# Official-source hosts worth trusting for 门票/开放时间. Ordered: government
# and scenic-area domains first, then the aggregators that are usually right
# but occasionally stale.
_OFFICIAL_HINTS = (".gov.cn", ".org.cn", "12301", "官网")
_AGGREGATORS = ("bendibao.com", "mafengwo.cn", "dianping.com", "ctrip.com", "trip.com")


_KEY_HELP = """\
未找到 Exa API Key。任选一种方式配置：

  1) 环境变量（临时）
       PowerShell:  $env:EXA_API_KEY = "你的KEY"
       bash:        export EXA_API_KEY="你的KEY"

  2) 用户级配置文件（推荐）
       把 Key 单独写进一行：  ~/.claude/.exa-key

申请与用量：https://dashboard.exa.ai
  ⚠ Exa 按次计费（实测 /search $0.007、/contents $0.001、/answer $0.005），
    不是免费额度。跑批量前先用 --budget 设上限。

Key 不会被写进本仓库的任何文件。"""


def load_key(explicit=None):
    if explicit:
        return explicit.strip()
    env = os.environ.get("EXA_API_KEY", "").strip()
    if env:
        return env
    for path in (os.path.join(os.getcwd(), ".exa-key"),
                 os.path.join(os.path.expanduser("~"), ".claude", ".exa-key")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        line = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return line
        except OSError:
            continue
    sys.exit(_KEY_HELP)


class Spend:
    """Tracks what this run has cost and refuses to blow past --budget."""

    def __init__(self, budget=None):
        self.budget = budget
        self.total = 0.0
        self.calls = 0

    def check(self, path):
        price = _PRICE.get(path, 0.0)
        if self.budget is not None and self.total + price > self.budget:
            raise BudgetExceeded(
                "预算 ${:.3f} 已用尽（已花 ${:.3f}，本次还需 ${:.3f}）。"
                "调高 --budget 或减少查询量。".format(self.budget, self.total, price))

    def add(self, path, reported=None):
        self.total += reported if reported is not None else _PRICE.get(path, 0.0)
        self.calls += 1

    def line(self):
        return "  本次运行：{} 次调用，约 ${:.3f}".format(self.calls, self.total)


class BudgetExceeded(RuntimeError):
    pass


class ApiError(RuntimeError):
    def __init__(self, code, body):
        self.code, self.body = code, body
        hint = {
            401: "Key 无效或已停用——去 dashboard.exa.ai 确认",
            402: "账户余额不足或已超额——Exa 按次计费，去 dashboard.exa.ai 充值",
            429: "触发限速，稍后重试或降低并发",
        }.get(code)
        super().__init__("Exa API HTTP {}: {}".format(code, body[:200])
                         + ("\n  → " + hint if hint else ""))


def api(path, body, key, spend, retries=2):
    spend.check(path)
    data = json.dumps(body).encode("utf-8")
    headers = dict(_UA)
    headers.update({"x-api-key": key, "Content-Type": "application/json"})
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(BASE + path, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            break
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", "replace")
            # 4xx other than rate-limit means the request was wrong; don't retry.
            if exc.code != 429 or attempt == retries:
                raise ApiError(exc.code, body_text) from exc
            time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == retries:
                raise RuntimeError("请求失败（重试 {} 次后）：{}".format(retries, exc)) from exc
            time.sleep(0.8 * (attempt + 1))

    reported = (payload.get("costDollars") or {}).get("total")
    spend.add(path, reported)
    return payload


# Words that mark an actual fact sentence, as opposed to site chrome. Ordered
# by how often they carry the number we came for.
_MAX_WINDOW = 700

_FACT_KEYS = ("开放时间", "入园时间", "闭园", "清园", "营业时间",
              "门票", "票价", "价格", "元/人", "免票", "免费", "优惠", "半价",
              "预约", "限流", "限量", "放票", "售票", "退票", "实名")


def fact_windows(text, window=150, limit=5):
    """Pull out the passages that actually mention hours/prices/booking.

    Official pages open with a wall of navigation links; a plain prefix of the
    text is mostly menu. Returns de-overlapped windows around the first hits,
    in document order, or None when nothing matches (caller then falls back to
    the plain prefix rather than hiding the page).
    """
    flat = " ".join((text or "").split())
    if not flat:
        return None
    spans = []
    for key in _FACT_KEYS:
        start = 0
        while True:
            i = flat.find(key, start)
            if i < 0:
                break
            spans.append((max(0, i - window // 3), min(len(flat), i + window)))
            start = i + len(key)
            if len(spans) > 60:      # pathological pages; enough to rank from
                break
    if not spans:
        return None
    spans.sort()
    merged = [list(spans[0])]
    for lo, hi in spans[1:]:
        if lo <= merged[-1][1] + 20:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])

    out = []
    for lo, hi in merged:
        chunk = flat[lo:hi]
        # Site navigation menus contain these very words ("开放时间 票务服务
        # 观光车服务 …") and matched above. A real fact sentence carries the
        # number we came for; a menu never does. Measured on panda.org.cn,
        # this drops the 400-char nav block and keeps the ticket table.
        if not re.search(r"\d", chunk):
            continue
        # A fact-dense page merges into one giant span; cap it so the caller
        # gets a readable excerpt instead of the whole document.
        if len(chunk) > _MAX_WINDOW:
            chunk = chunk[:_MAX_WINDOW] + "…（本段更长，用 fetch 读全文）"
        out.append(chunk)
        if len(out) >= limit:
            break
    return out or None


def _host(url):
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except ValueError:
        return ""


def _rank(url):
    """Official pages first, aggregators second, everything else last."""
    host = _host(url)
    if any(h in host for h in _OFFICIAL_HINTS):
        return 0
    if any(h in host for h in _AGGREGATORS):
        return 2
    return 1


def _source_kind(url):
    return {0: "官方", 2: "聚合站", 1: "其它"}[_rank(url)]


def verify_one(name, city, key, spend, chars=1200, want=3):
    """Find the official page for one stop and return ITS OWN TEXT.

    No summarising: the caller reads the returned text and decides what is
    quotable. That is the whole point — a summary cannot be cited.
    """
    query = "{} {} 开放时间 门票 预约".format(city or "", name).strip()
    found = api("/search", {"query": query, "numResults": 8,
                            "contents": {"text": {"maxCharacters": chars}}},
                key, spend)
    rows = found.get("results") or []
    if not rows:
        return {"query": name, "found": False, "reason": "no_results"}

    rows.sort(key=lambda r: _rank(r.get("url", "")))
    picked = []
    for r in rows[:want]:
        text = (r.get("text") or "").strip()
        picked.append({
            "title": r.get("title"),
            "url": r.get("url"),
            "source_kind": _source_kind(r.get("url", "")),
            "published": r.get("publishedDate"),
            "text": text,
            "fact_windows": fact_windows(text),
        })
    return {
        "query": name,
        "found": True,
        "sources": picked,
        "checked_on": date.today().isoformat(),
    }


def cmd_verify(args, key, spend):
    names = list(args.names)
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            names += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    if not names:
        sys.exit("没有要核验的地点：给出地点名，或用 --file 指定一行一个的清单")

    results = []
    for n in names:
        try:
            results.append(verify_one(n, args.city, key, spend, args.chars, args.sources))
        except BudgetExceeded as exc:
            print("\n⚠ {}".format(exc))
            break

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        print(spend.line(), file=sys.stderr)
        return 0

    print("\n官方信息核验 · {} · {}\n".format(args.city or "全国", date.today().isoformat()))
    for r in results:
        if not r["found"]:
            print("  ✗ {}  未找到可用来源（{}）".format(r["query"], r["reason"]))
            print("     → 按契约降级：写「以官网为准」，不要填具体时间/票价\n")
            continue
        print("  ▸ {}".format(r["query"]))
        for s in r["sources"]:
            date_note = "  发布 {}".format(s["published"][:10]) if s.get("published") else ""
            print("     [{}] {}{}".format(s["source_kind"], s["title"], date_note))
            print("     {}".format(s["url"]))
            windows = s.get("fact_windows")
            if windows:
                print("     ┌ 原文命中段 ───────────────────────")
                for w in windows:
                    print("     │ …{}…".format(w))
                print("     └───────────────────────────────────")
            else:
                body = " ".join((s["text"] or "").split())
                if body:
                    print("     ┌ 原文（未命中关键词，给开头）──────")
                    for i in range(0, min(len(body), 400), 100):
                        print("     │ {}".format(body[i:i + 100]))
                    print("     └───────────────────────────────────")
            print()
    print("  ⚠ 上面是页面原文，不是结论。**你自己读**，读到的才可写成具体值，")
    print("    并标 `Exa 实查 YYYY-MM-DD` + 来源 URL；没读到就照契约写 hedge。")
    print("  ⚠ 聚合站（本地宝/马蜂窝/点评）常年不更新，与官方冲突时**以官方为准**。")
    print(spend.line())
    print()
    return 0


def cmd_fetch(args, key, spend):
    payload = api("/contents", {"urls": args.urls,
                                "text": {"maxCharacters": args.chars}}, key, spend)
    rows = payload.get("results") or []
    if args.json:
        print(json.dumps({"results": rows, "checked_on": date.today().isoformat()},
                         ensure_ascii=False, indent=2))
        print(spend.line(), file=sys.stderr)
        return 0
    for r in rows:
        print("\n{}".format(r.get("url")))
        print("{}\n".format(r.get("title") or ""))
        print(r.get("text") or "(无正文)")
    print("\n" + spend.line() + "\n")
    return 0


def cmd_search(args, key, spend):
    body = {"query": args.query, "numResults": args.limit}
    if args.site:
        body["includeDomains"] = args.site
    if args.text:
        body["contents"] = {"text": {"maxCharacters": args.chars}}
    payload = api("/search", body, key, spend)
    rows = payload.get("results") or []
    if args.json:
        print(json.dumps({"results": rows}, ensure_ascii=False, indent=2))
        print(spend.line(), file=sys.stderr)
        return 0
    print("\n「{}」{}\n".format(args.query,
                              " · 限定 " + ",".join(args.site) if args.site else ""))
    for r in rows:
        pub = "  {}".format(r["publishedDate"][:10]) if r.get("publishedDate") else ""
        print("  [{}] {}{}".format(_source_kind(r.get("url", "")), r.get("title"), pub))
        print("       {}".format(r.get("url")))
        if args.text and r.get("text"):
            print("       {}".format(" ".join(r["text"].split())[:160]))
    print("\n" + spend.line() + "\n")
    return 0


def cmd_answer(args, key, spend):
    payload = api("/answer", {"query": args.query}, key, spend)
    print("\n{}\n".format(payload.get("answer") or "(无答案)"))
    cites = payload.get("citations") or []
    if cites:
        print("引用来源 {} 条：".format(len(cites)))
        for c in cites[:8]:
            print("  [{}] {}".format(_source_kind(c.get("url", "")), c.get("title", "")))
            print("       {}".format(c.get("url")))
    print("\n  ⚠ 这段答案是 Exa 的模型综合出来的，**不是一手资料**。")
    print("    要写进行程，请对上面的来源跑 fetch 读原文核对后再写。")
    print(spend.line() + "\n")
    return 0


def cmd_selfcheck(args, key, spend):
    print("\nExa · 连通性自检\n")
    print("  Key: {}…{}（长度 {}）".format(key[:8], key[-4:], len(key)))
    ok = True
    try:
        d = api("/search", {"query": "成都大熊猫繁育研究基地 开放时间", "numResults": 3}, key, spend)
        rows = d.get("results") or []
        print("  ✓ 搜索          返回 {} 条".format(len(rows)))
        official = [r for r in rows if _rank(r.get("url", "")) == 0]
        if official:
            print("  ✓ 中文查询      命中官方站点 {}".format(_host(official[0]["url"])))
        else:
            print("  ⚠ 中文查询      未命中官方站点（{}）".format(
                ", ".join(_host(r.get("url", "")) for r in rows[:3])))
    except (ApiError, RuntimeError) as exc:
        ok = False
        print("  ✗ 搜索          {}".format(exc))

    if ok:
        try:
            d2 = api("/contents", {"urls": ["https://m.panda.org.cn/cn/service/opentime/"],
                                   "text": {"maxCharacters": 200}}, key, spend)
            got = (d2.get("results") or [{}])[0].get("text") or ""
            print("  ✓ 抓取正文      {} 字符".format(len(got)))
        except (ApiError, RuntimeError) as exc:
            ok = False
            print("  ✗ 抓取正文      {}".format(exc))

    print("\n  计费：/search $0.007、/contents $0.001、/answer $0.005（实测）")
    print(spend.line())
    print("  结论：{}\n".format("可用" if ok else "有项目未通过，见上"))
    return 0 if ok else 1


def build_parser():
    p = argparse.ArgumentParser(
        prog="exa_facts.py",
        description="Exa · 给 trip-planner 取官方门票/开放时间/预约信息的原文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="按次计费。verify 每个点约 $0.008，跑批量前用 --budget 设上限。\n"
               "--key / --json / --budget 写在子命令后面。")
    # On the subcommands, not the top level — see tencent_lbs.py for why.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--key", help="API Key（默认读 $EXA_API_KEY 或 ~/.claude/.exa-key）")
    common.add_argument("--json", action="store_true", help="输出 JSON")
    common.add_argument("--budget", type=float, metavar="USD",
                        help="本次运行的花费上限（美元），超过就停")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", parents=[common], help="核验一个/一批地点的开放时间·门票·预约（给原文）")
    v.add_argument("names", nargs="*")
    v.add_argument("--file", help="从文件读，一行一个")
    v.add_argument("--city", help="限定城市，建议给")
    v.add_argument("--sources", type=int, default=3, help="每个点保留几条来源")
    v.add_argument("--chars", type=int, default=1200, help="每条来源取多少字符正文")
    v.set_defaults(func=cmd_verify)

    f = sub.add_parser("fetch", parents=[common], help="抓指定 URL 的正文（最便宜，$0.001/条）")
    f.add_argument("urls", nargs="+")
    f.add_argument("--chars", type=int, default=3000)
    f.set_defaults(func=cmd_fetch)

    s = sub.add_parser("search", parents=[common], help="搜索，可用 --site 限定域名")
    s.add_argument("query")
    s.add_argument("--site", nargs="+", metavar="DOMAIN",
                   help="限定域名，如 xiaohongshu.com dianping.com")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--text", action="store_true", help="同时取正文片段")
    s.add_argument("--chars", type=int, default=500)
    s.set_defaults(func=cmd_search)

    a = sub.add_parser("answer", parents=[common], help="直接问答（仅用于定位来源，不可当实查）")
    a.add_argument("query")
    a.set_defaults(func=cmd_answer)

    c = sub.add_parser("selfcheck", parents=[common], help="连通性 + 中文查询质量自检")
    c.set_defaults(func=cmd_selfcheck)
    return p


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args()
    key = load_key(args.key)
    spend = Spend(args.budget)
    try:
        sys.exit(args.func(args, key, spend))
    except BudgetExceeded as exc:
        sys.exit("\n⚠ {}\n".format(exc))
    except ApiError as exc:
        sys.exit("\n{}\n".format(exc))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
