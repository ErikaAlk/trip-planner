#!/usr/bin/env python3
r"""tencent_lbs.py — Tencent Location Service client for trip-planner.

Replaces the click-through-a-map-website parts of Step 3.5 with real API
calls: POI coordinates, drive/transit times, fares, tolls, and distance
matrices for geographic clustering.

Usage:
    python3 tencent_lbs.py selfcheck
    python3 tencent_lbs.py geocode 宽窄巷子 武侯祠 杜甫草堂 --city 成都
    python3 tencent_lbs.py geocode --file stops.txt --city 成都 --json
    python3 tencent_lbs.py route --from 宽窄巷子 --to 武侯祠 --city 成都 --mode transit
    python3 tencent_lbs.py matrix --file stops.txt --city 成都 --mode driving
    python3 tencent_lbs.py search 火锅 --city 成都 --near 30.66,104.06 --radius 1500
    py       tencent_lbs.py ...                                       # Windows

API key resolution (first hit wins) — the key is NEVER stored in this repo:
    1. --key on the command line
    2. $TENCENT_LBS_KEY
    3. ./.tencent-lbs-key                  (cwd, overrides the user default)
    4. ~/.claude/.tencent-lbs-key          (single line, the key)
Run `selfcheck` for setup instructions if none is found.

TWO THINGS THIS SCRIPT EXISTS TO PREVENT
----------------------------------------
1. COORDINATE SYSTEM. Tencent returns GCJ-02 ("Mars coordinates"). The
   trip-planner map is Leaflet + OpenStreetMap, which is WGS-84. Feeding
   GCJ-02 straight into Leaflet puts every pin ~500 m off — reliably one
   street over. This script converts to WGS-84 by default (`--coord`
   overrides). Verified against Tencent's own /ws/coord/v1/translate:
   round-trip error 0.00 m.

2. FALSE POSITIVES. Tencent's place search does NOT return empty for a
   nonsense query — it returns status=0 with a page of unrelated POIs.
   Querying a nonexistent place returns residential compounds and township
   names with perfectly formatted coordinates. Blindly taking data[0] writes
   a fabricated coordinate into the itinerary wearing an "API-verified"
   badge, which is worse than an obvious guess. Every lookup here is scored
   for relevance and low-confidence hits are reported as NOT_FOUND so the
   caller falls back to a hedge per the skill's data-integrity contract.
"""

import argparse
import json
import math
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

BASE = "https://apis.map.qq.com"

# Personal-tier quota is 5 QPS / 10,000 calls per day (lbs.qq.com guide-quota).
# 0.22s (=4.5 QPS) sat close enough to the ceiling that a real run still got
# rejected as too fast, so back off to ~2.9 QPS. Trip planning issues tens of
# calls, not thousands — the extra second total costs nothing.
_MIN_INTERVAL = 0.35

# Relevance thresholds for "did the search actually find what I asked for".
_CONF_OK = 0.70
_CONF_WARN = 0.40

_UA = {"User-Agent": "trip-planner-skill/1.0 (+https://github.com/ErikaAlk/trip-planner)"}


# --------------------------------------------------------------------------
# API key
# --------------------------------------------------------------------------

_KEY_HELP = """\
未找到腾讯位置服务 API Key。任选一种方式配置：

  1) 环境变量（临时）
       PowerShell:  $env:TENCENT_LBS_KEY = "你的KEY"
       bash:        export TENCENT_LBS_KEY="你的KEY"

  2) 用户级配置文件（推荐，一次配置长期有效）
       把 Key 单独写进一行：  ~/.claude/.tencent-lbs-key

免费申请：https://lbs.qq.com/dev/console/application/mine
  控制台 → 应用管理 → 我的应用 → 创建应用 → 添加 Key
  → 启用「WebServiceAPI」，个人开发者额度 10,000 次/日、5 次/秒
  → 授权方式选「无」或把本机 IP 加白名单；若开了签名校验(SK)本脚本不支持

Key 不会被写进本仓库的任何文件，也不要粘贴到 SKILL.md / 行程 HTML 里。"""


def load_key(explicit=None):
    """Resolve the API key, or exit with setup instructions."""
    if explicit:
        return explicit.strip()
    env = os.environ.get("TENCENT_LBS_KEY", "").strip()
    if env:
        return env
    # Project-local first: a key dropped in the working directory is meant to
    # override the user-level default for that one project.
    candidates = [
        os.path.join(os.getcwd(), ".tencent-lbs-key"),
        os.path.join(os.path.expanduser("~"), ".claude", ".tencent-lbs-key"),
    ]
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    # tolerate `TENCENT_LBS_KEY=xxx` and `# comment` lines
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        line = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return line
        except OSError:
            continue
    sys.exit(_KEY_HELP)


# --------------------------------------------------------------------------
# GCJ-02 <-> WGS-84
# --------------------------------------------------------------------------

_A = 6378245.0                      # Krasovsky 1940 semi-major axis
_EE = 0.00669342162296594323        # and its eccentricity squared


def _tf_lng(x, y):
    r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    r += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return r


def _tf_lat(x, y):
    r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    r += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    r += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    r += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return r


def _out_of_china(lat, lng):
    return not (0.8293 <= lat <= 55.8271 and 72.004 <= lng <= 137.8347)


def wgs84_to_gcj02(lat, lng):
    if _out_of_china(lat, lng):
        return lat, lng
    d_lat, d_lng = _tf_lat(lng - 105.0, lat - 35.0), _tf_lng(lng - 105.0, lat - 35.0)
    rad = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    d_lng = (d_lng * 180.0) / (_A / sqrt_magic * math.cos(rad) * math.pi)
    return lat + d_lat, lng + d_lng


def gcj02_to_wgs84(lat, lng):
    """Invert the GCJ-02 offset numerically.

    There is no closed form, so iterate the forward transform. Eight rounds
    converge well past the precision Tencent reports; checked against
    /ws/coord/v1/translate on four cities with 0.00 m round-trip error.
    """
    if _out_of_china(lat, lng):
        return lat, lng
    w_lat, w_lng = lat, lng
    for _ in range(8):
        g_lat, g_lng = wgs84_to_gcj02(w_lat, w_lng)
        w_lat += lat - g_lat
        w_lng += lng - g_lng
    return w_lat, w_lng


def haversine_m(a, b):
    """Great-circle distance in metres between two (lat, lng) pairs."""
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    d_p, d_l = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(d_p / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_l / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class _Throttle:
    """Spaces calls out so a burst never trips the 5 QPS ceiling."""

    def __init__(self, interval=_MIN_INTERVAL):
        self.interval = interval
        self._last = 0.0

    def wait(self):
        gap = time.monotonic() - self._last
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self._last = time.monotonic()


_throttle = _Throttle()

# Only codes confirmed against the live API are spelled out; anything else
# falls through to Tencent's own message so this never invents an explanation.
# Hints add ACTION, never a restatement of Tencent's message — an earlier
# version paraphrased 120 as a daily-quota error when the live message says
# per-second, i.e. the paraphrase was simply wrong. Tencent's own message is
# already accurate Chinese; only say what it doesn't.
_STATUS_HINT = {
    311: "检查 Key 是否复制完整（应为 5 段短横线分隔）",
    190: "Key 格式对但不存在——确认没删除、且用的是 WebServiceAPI 那把",
    348: "检查参数拼写；城市名用中文全称，坐标用 lat,lng",
    110: "控制台给这把 Key 配了域名/IP 白名单——把本机 IP 加进去，或改成无限制",
    111: "这把 Key 开了 SK 签名校验，本脚本不支持——另建一把不开签名的 Key",
    120: "放慢调用（脚本已限速，通常是同时跑了多个进程）；若确是当日 10,000 次用尽，等次日重置",
    121: "同上：降低并发后重试",
}

# Rate-limit codes worth retrying: the request was fine, we were just too fast.
_RATE_LIMITED = (120, 121)


class ApiError(RuntimeError):
    def __init__(self, status, message):
        self.status, self.message = status, message
        hint = _STATUS_HINT.get(status)
        super().__init__("腾讯 API 返回 status={}: {}".format(status, message)
                         + ("\n  → " + hint if hint else ""))


def api(path, params, key, retries=2):
    """One throttled GET. Retries transport errors, never business errors."""
    query = dict(params)
    query["key"] = key
    url = BASE + path + "?" + urllib.parse.urlencode(query)
    for attempt in range(retries + 1):
        _throttle.wait()
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt == retries:
                raise RuntimeError("请求失败（重试 {} 次后）：{}".format(retries, exc)) from exc
            time.sleep(0.6 * (attempt + 1))

    status = payload.get("status")
    if status != 0:
        # A rate-limit rejection means we were merely too fast, not wrong —
        # back off hard and give it one more go.
        if status in _RATE_LIMITED and retries:
            time.sleep(1.5)
            return api(path, params, key, retries=0)
        raise ApiError(status, payload.get("message", ""))
    return payload


# --------------------------------------------------------------------------
# Relevance scoring
# --------------------------------------------------------------------------

_NOISE = set("市区县镇乡村街道路号的-—·()[]【】（） 　")


def coverage(query, title):
    """Fraction of the query's meaningful characters present in the title.

    Deliberately crude: Chinese POI names are short and the failure mode we
    guard against is total non-matches (asking for 宽窄巷子 and being handed
    富丽碧蔓汀), not near-misses. Scores 1.00 on every real lookup tested and
    0.00 on nonsense queries.
    """
    chars = {c for c in query if c not in _NOISE}
    if not chars:
        return 0.0
    return sum(1 for c in chars if c in title) / len(chars)


def _confidence(score):
    if score >= _CONF_OK:
        return "high"
    if score >= _CONF_WARN:
        return "low"
    return "none"


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def _disp_width(text):
    """Terminal width of a string: CJK glyphs occupy two cells."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _clip(text, cells):
    """Truncate to at most `cells` display cells."""
    out, used = "", 0
    for c in text:
        w = 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        if used + w > cells:
            break
        out, used = out + c, used + w
    return out


def _pad(text, cells, right=False):
    gap = " " * max(0, cells - _disp_width(text))
    return gap + text if right else text + gap


_NEED_CITY = (
    "缺 --city。腾讯的地点搜索必须带搜索范围：不给城市会直接报参数错误，"
    "而 region(中国,0) 这类写法虽然返回成功、结果却是空的。\n"
    "  例：python3 tencent_lbs.py {} --city 成都"
)


def _looks_like_coords(text):
    """`30.66,104.06` 形式的输入不需要城市。"""
    parts = text.split(",")
    if len(parts) != 2:
        return False
    try:
        float(parts[0]), float(parts[1])
    except ValueError:
        return False
    return True


def _convert(lat, lng, coord):
    return (lat, lng) if coord == "gcj02" else gcj02_to_wgs84(lat, lng)


def geocode_one(name, city, key, coord="wgs84"):
    """Resolve one POI name to coordinates, with a relevance verdict."""
    params = {"keyword": name, "page_size": 5}
    if city:
        params["boundary"] = "region({},0)".format(city)
    try:
        payload = api("/ws/place/v1/search", params, key)
    except ApiError as exc:
        return {"query": name, "found": False,
                "reason": "api_error:{}".format(exc.status), "message": exc.message}

    rows = payload.get("data") or []
    if not rows:
        return {"query": name, "found": False, "reason": "empty"}

    scored = sorted(rows, key=lambda r: coverage(name, r.get("title", "")), reverse=True)
    best = scored[0]
    score = coverage(name, best.get("title", ""))
    conf = _confidence(score)
    if conf == "none":
        # This is the trap: Tencent handed back well-formed but unrelated POIs.
        return {"query": name, "found": False, "reason": "no_relevant_match",
                "best_guess": best.get("title"), "score": round(score, 2)}

    lat, lng = _convert(best["location"]["lat"], best["location"]["lng"], coord)
    ad = best.get("ad_info") or {}
    return {
        "query": name,
        "found": True,
        "title": best.get("title"),
        "lat": round(lat, 6),
        "lng": round(lng, 6),
        "coord_system": coord,
        "address": best.get("address"),
        "tel": best.get("tel") or None,
        "category": best.get("category"),
        "city": ad.get("city"),
        "district": ad.get("district"),
        "confidence": conf,
        "score": round(score, 2),
        "source": "腾讯位置服务 API 实查 " + date.today().isoformat(),
    }


def cmd_geocode(args, key):
    names = list(args.names)
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            names += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    if not names:
        sys.exit("没有要查的地点：给出地点名，或用 --file 指定一行一个的清单")
    if not args.city:
        sys.exit(_NEED_CITY.format("geocode 宽窄巷子"))

    results = [geocode_one(n, args.city, key, args.coord) for n in names]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return _exit_code(results)

    note = "（可直接填 Leaflet）" if args.coord == "wgs84" else "（腾讯/高德用，勿填 Leaflet）"
    print("\n坐标查询 · {} · 输出坐标系 {}{}\n".format(
        args.city or "全国", args.coord.upper(), note))
    for r in results:
        if not r["found"]:
            print("  ✗ {}".format(r["query"]))
            if r["reason"] == "no_relevant_match":
                print("      查无匹配（最接近的是「{}」，相关度 {}，判定为不相关）".format(
                    r["best_guess"], r["score"]))
                print("      → 按数据诚信契约降级：不要写具体坐标，改用城区级近似并注明")
            elif r["reason"] == "empty":
                print("      腾讯返回空结果")
            else:
                print("      {}".format(r.get("message", r["reason"])))
            continue
        flag = "" if r["confidence"] == "high" else "  ⚠ 低置信度，请人工确认"
        print("  ✓ {} → {}{}".format(r["query"], r["title"], flag))
        print("      {}, {}   [{}]".format(r["lat"], r["lng"], r["coord_system"].upper()))
        print("      {}{}".format(r["address"], "  ☎ " + r["tel"] if r["tel"] else ""))
        print("      {}".format(r["category"]))
    print()
    return _exit_code(results)


def _exit_code(results):
    return 0 if all(r["found"] for r in results) else 3


_MODES = ("driving", "transit", "walking", "bicycling")


def _resolve_point(text, city, key):
    """Accept either a raw `lat,lng` (assumed WGS-84) or a POI name."""
    parts = text.split(",")
    if len(parts) == 2:
        try:
            lat, lng = float(parts[0]), float(parts[1])
            # Route APIs speak GCJ-02, so push WGS-84 input back into it.
            g_lat, g_lng = wgs84_to_gcj02(lat, lng)
            return "{:.6f},{:.6f}".format(g_lat, g_lng), text
        except ValueError:
            pass
    hit = geocode_one(text, city, key, coord="gcj02")
    if not hit["found"]:
        sys.exit("起点/终点定位失败：{}（{}）——不要凭印象填坐标，换个更完整的名称重试，"
                 "或按契约降级为不写具体车程".format(text, hit["reason"]))
    return "{},{}".format(hit["lat"], hit["lng"]), hit["title"]


def cmd_route(args, key):
    if not args.city and not (_looks_like_coords(args.origin)
                              and _looks_like_coords(args.dest)):
        sys.exit(_NEED_CITY.format("route --from 宽窄巷子 --to 武侯祠"))
    origin, o_label = _resolve_point(args.origin, args.city, key)
    dest, d_label = _resolve_point(args.dest, args.city, key)
    payload = api("/ws/direction/v1/{}/".format(args.mode),
                  {"from": origin, "to": dest}, key)
    routes = (payload.get("result") or {}).get("routes") or []
    if not routes:
        sys.exit("没有返回可用路线（{}）".format(args.mode))

    out = []
    for rt in routes[: args.limit]:
        item = {
            "mode": args.mode,
            "distance_m": rt.get("distance"),
            "distance_km": round((rt.get("distance") or 0) / 1000.0, 1),
            # direction API reports MINUTES (matrix reports seconds — do not mix)
            "duration_min": rt.get("duration"),
        }
        if args.mode == "driving":
            item["toll_yuan"] = rt.get("toll")
            item["traffic_lights"] = rt.get("traffic_light_count")
        if args.mode == "transit":
            price = rt.get("price")          # fare comes in 分
            item["fare_yuan"] = round(price / 100.0, 2) if price is not None else None
            legs = []
            for step in rt.get("steps") or []:
                if step.get("mode") != "TRANSIT":
                    continue
                lines = step.get("lines") or []
                for line in lines:
                    legs.append(line.get("title"))
                if not lines and step.get("title"):
                    legs.append(step.get("title"))
            item["lines"] = [l for l in legs if l]
            item["transfers"] = max(0, len(item["lines"]) - 1)
        out.append(item)

    result = {"from": o_label, "to": d_label, "mode": args.mode, "routes": out,
              "source": "腾讯位置服务 API 实查 " + date.today().isoformat()}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    label = {"driving": "驾车", "transit": "公交/地铁",
             "walking": "步行", "bicycling": "骑行"}[args.mode]
    print("\n{}：{} → {}\n".format(label, o_label, d_label))
    for i, r in enumerate(out, 1):
        head = "  方案{}  {} km · {} 分钟".format(i, r["distance_km"], r["duration_min"])
        if r.get("fare_yuan") is not None:
            head += " · ¥{:.2f}".format(r["fare_yuan"])
        if r.get("toll_yuan"):
            head += " · 过路费 ¥{}".format(r["toll_yuan"])
        print(head)
        if r.get("lines"):
            print("          {}（换乘 {} 次）".format(" → ".join(r["lines"]), r["transfers"]))
        if r.get("traffic_lights") is not None:
            print("          红绿灯 {} 个".format(r["traffic_lights"]))
    if args.mode == "driving":
        print("\n  注：这是理论净车程。带老人小孩 / 山路 / 停车拍照，排日程按 ×1.2–1.3。")
    print()
    return 0


# The matrix endpoint bills PER ELEMENT against the 5/sec ceiling, not per
# request: measured 2x2 (4 elements) OK, 3x3 (9) and 4x4 (16) both rejected as
# "每秒请求量已达到上限" even with 2.5 s between calls. So never ask for the
# whole grid at once — walk it one origin at a time, <=4 destinations per call,
# with a full second in between.
_MATRIX_CHUNK = 4
_MATRIX_PAUSE = 1.1


def _fetch_matrix(resolved, mode, key):
    """Fetch an N*N matrix in element-budget-sized pieces."""
    grid = []
    for _, origin in resolved:
        row = []
        for start in range(0, len(resolved), _MATRIX_CHUNK):
            chunk = resolved[start:start + _MATRIX_CHUNK]
            if start or grid:
                time.sleep(_MATRIX_PAUSE)
            payload = api("/ws/distance/v1/matrix",
                          {"mode": mode, "from": origin,
                           "to": ";".join(p for _, p in chunk)}, key)
            rows = (payload.get("result") or {}).get("rows") or []
            elements = rows[0].get("elements", []) if rows else []
            for e in elements:
                row.append({
                    "distance_m": e.get("distance"),
                    # matrix reports SECONDS; direction reports minutes
                    "duration_min": round((e.get("duration") or 0) / 60.0, 1),
                })
        grid.append(row)
    return grid


def cmd_matrix(args, key):
    names = list(args.names)
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            names += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    if len(names) < 2:
        sys.exit("距离矩阵至少需要 2 个点")
    if not args.city:
        sys.exit(_NEED_CITY.format("matrix 宽窄巷子 武侯祠"))
    if len(names) > 8:
        sys.exit("一次最多 8 个点（收到 {} 个）——按天拆开跑。矩阵按 N×N 个元素"
                 "计入配额，8 个点已是 64 次调用 + 约 16 秒".format(len(names)))

    resolved = []
    for n in names:
        hit = geocode_one(n, args.city, key, coord="gcj02")
        if not hit["found"]:
            sys.exit("定位失败：{}（{}）——先用 geocode 逐个确认名称".format(n, hit["reason"]))
        resolved.append((hit["title"], "{},{}".format(hit["lat"], hit["lng"])))

    labels = [t for t, _ in resolved]
    grid = _fetch_matrix(resolved, args.mode, key)

    if args.json:
        print(json.dumps({"mode": args.mode, "labels": labels, "matrix": grid,
                          "source": "腾讯位置服务 API 实查 " + date.today().isoformat()},
                         ensure_ascii=False, indent=2))
        return 0

    mode_cn = {"driving": "驾车", "walking": "步行", "bicycling": "骑行"}[args.mode]
    n = len(labels)
    short = [_clip(l, 10) for l in labels]
    head_w = max(_disp_width(s) for s in short) + 2
    print("\n{}距离矩阵（上行=公里 / 下行=分钟）· {}\n".format(mode_cn, args.city or ""))
    print(_pad("", head_w) + "".join(_pad(s, 11, right=True) for s in short))
    for i in range(n):
        km, mn = [], []
        for j in range(n):
            if i == j:
                # Self-to-self is meaningless, and in multi-destination mode
                # Tencent doesn't return 0 for it anyway — it snaps to the
                # nearest road and reports the loop back (measured 319 m for
                # 宽窄巷子). Printing "—" beats printing a number nobody
                # should act on.
                km.append(_pad("—", 11, right=True))
                mn.append(_pad("", 11, right=True))
                continue
            km.append(_pad("{:.1f}".format(grid[i][j]["distance_m"] / 1000), 11, right=True))
            mn.append(_pad("{:.0f}".format(grid[i][j]["duration_min"]), 11, right=True))
        print(_pad(short[i], head_w) + "".join(km))
        print(_pad("", head_w) + "".join(mn))
    print("\n  聚类用法：同一天的点尽量彼此 <20 分钟，跨簇的挪到别天。")
    print("  ⚠ 这里的数字只用于判断远近。写进行程卡片的具体车程必须用 route 单独查——")
    print("    两者路线算法不同，实测同一段可差 4 km / 10 分钟。")
    print()
    return 0


def cmd_search(args, key):
    params = {"keyword": args.keyword, "page_size": args.limit}
    if args.near:
        lat, lng = (float(x) for x in args.near.split(","))
        g_lat, g_lng = wgs84_to_gcj02(lat, lng)
        params["boundary"] = "nearby({:.6f},{:.6f},{})".format(g_lat, g_lng, args.radius)
        params["orderby"] = "_distance"
    elif args.city:
        params["boundary"] = "region({},0)".format(args.city)
    else:
        sys.exit("需要 --city 或 --near 之一来限定搜索范围")

    payload = api("/ws/place/v1/search", params, key)
    rows = payload.get("data") or []
    out = []
    for r in rows:
        lat, lng = _convert(r["location"]["lat"], r["location"]["lng"], args.coord)
        out.append({"title": r.get("title"), "lat": round(lat, 6), "lng": round(lng, 6),
                    "coord_system": args.coord, "address": r.get("address"),
                    "tel": r.get("tel") or None, "category": r.get("category"),
                    "distance_m": r.get("_distance")})
    if args.json:
        print(json.dumps({"keyword": args.keyword, "count": payload.get("count"),
                          "results": out,
                          "source": "腾讯位置服务 API 实查 " + date.today().isoformat()},
                         ensure_ascii=False, indent=2))
        return 0
    print("\n「{}」· 共 {} 条，显示前 {}\n".format(args.keyword, payload.get("count"), len(out)))
    for r in out:
        print("  {}   [{}, {}]".format(r["title"], r["lat"], r["lng"]))
        print("      {}{}".format(r["address"], "  ☎ " + r["tel"] if r["tel"] else ""))
        print("      {}".format(r["category"]))
    print("\n  注意：搜索结果按腾讯排序给出，不代表推荐度。评分/口碑仍需浏览器实查。")
    print()
    return 0


def cmd_selfcheck(args, key):
    print("\n腾讯位置服务 · 连通性自检\n")
    print("  Key: {}…{}（长度 {}）".format(key[:5], key[-4:], len(key)))
    ok = True
    try:
        hit = geocode_one("天安门", "北京", key)
        if hit["found"]:
            print("  ✓ 地点搜索      天安门 → {}, {} [WGS-84]".format(hit["lat"], hit["lng"]))
        else:
            ok = False
            print("  ✗ 地点搜索      {}".format(hit["reason"]))
    except (ApiError, RuntimeError) as exc:
        ok = False
        print("  ✗ 地点搜索      {}".format(exc))

    for path, params, label in (
        ("/ws/direction/v1/driving/",
         {"from": "39.984154,116.307490", "to": "39.908823,116.397470"}, "驾车路线"),
        ("/ws/distance/v1/matrix",
         {"mode": "driving", "from": "39.984154,116.307490", "to": "39.908823,116.397470"},
         "距离矩阵"),
    ):
        try:
            api(path, params, key)
            print("  ✓ {}".format(label))
        except (ApiError, RuntimeError) as exc:
            ok = False
            print("  ✗ {}      {}".format(label, exc))

    # Guard-rail check: the false-positive trap must actually be caught.
    trap = geocode_one("这个地方根本不存在zzzqqq", "成都", key)
    if trap["found"]:
        ok = False
        print("  ✗ 误报防护      未拦住无关结果（返回了「{}」）".format(trap.get("title")))
    else:
        print("  ✓ 误报防护      无关查询被正确判定为 {}".format(trap["reason"]))

    print("\n  额度：个人开发者 10,000 次/日、5 次/秒（lbs.qq.com 配额页）")
    print("  结论：{}\n".format("可用" if ok else "有项目未通过，见上"))
    return 0 if ok else 1


# --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="tencent_lbs.py",
        description="腾讯位置服务 · trip-planner 取真实坐标/车程/票价",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="坐标默认输出 WGS-84（Leaflet/OSM 用）。腾讯原生是 GCJ-02，"
               "直接填进 Leaflet 会偏约 500 米。\n"
               "--key / --json 写在子命令后面，例：geocode 宽窄巷子 --city 成都 --json")
    # Shared options live on the SUBCOMMANDS, not the top level: putting them
    # in both makes argparse's subparser defaults clobber a top-level value,
    # so `--json geocode ...` would silently do nothing.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--key", help="API Key（默认读环境变量或 ~/.claude/.tencent-lbs-key）")
    common.add_argument("--json", action="store_true", help="输出 JSON，便于直接填进 TRIP 数据")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("geocode", parents=[common], help="地点名 → 坐标（带相关性校验）")
    g.add_argument("names", nargs="*", help="一个或多个地点名")
    g.add_argument("--file", help="从文件读，一行一个")
    g.add_argument("--city", help="限定城市（必需：腾讯搜索要求搜索范围）")
    g.add_argument("--coord", choices=("wgs84", "gcj02"), default="wgs84")
    g.set_defaults(func=cmd_geocode)

    r = sub.add_parser("route", parents=[common], help="两点间路线：距离/时长/票价/过路费")
    r.add_argument("--from", dest="origin", required=True, help="地点名或 lat,lng（WGS-84）")
    r.add_argument("--to", dest="dest", required=True)
    r.add_argument("--city")
    r.add_argument("--mode", choices=_MODES, default="driving")
    r.add_argument("--limit", type=int, default=3, help="最多显示几个方案")
    r.set_defaults(func=cmd_route)

    m = sub.add_parser("matrix", parents=[common], help="多点距离矩阵，用于地理聚类")
    m.add_argument("names", nargs="*")
    m.add_argument("--file")
    m.add_argument("--city")
    m.add_argument("--mode", choices=("driving", "walking", "bicycling"), default="driving")
    m.set_defaults(func=cmd_matrix)

    s = sub.add_parser("search", parents=[common], help="周边/关键词搜索：找餐厅、地铁站、酒店")
    s.add_argument("keyword")
    s.add_argument("--city")
    s.add_argument("--near", help="中心点 lat,lng（WGS-84）")
    s.add_argument("--radius", type=int, default=1000, help="--near 时的半径（米）")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--coord", choices=("wgs84", "gcj02"), default="wgs84")
    s.set_defaults(func=cmd_search)

    c = sub.add_parser("selfcheck", parents=[common], help="连通性 + 额度 + 误报防护自检")
    c.set_defaults(func=cmd_selfcheck)
    return p


def main():
    # Chinese POI names + ° / ¥ / — crash a GBK Windows console mid-run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args()
    key = load_key(args.key)
    try:
        sys.exit(args.func(args, key))
    except ApiError as exc:
        sys.exit("\n{}\n".format(exc))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
