# Research Playbook & Itinerary Logic (deep dive)

Companion to `SKILL.md`. Read this when researching transport/weather/places and when sequencing a
day. The golden rule throughout: **only state facts you actually found; never fabricate hours, prices,
addresses, or schedules.** A confidently wrong opening time is worse than an honest "以官网为准".

---

## 1. Web search patterns (the fast default)

Run focused searches and read 2–3 sources before asserting a fact. Useful query shapes:

**Transport (查询，不下单):**
- `"<出发地> 到 <目的地> 高铁 时刻表 票价"` · `"<出发地> <目的地> 火车 二等座 多少钱"`
- `"<from> to <to> flights <month> price"` · `"<航司> <航线> 直飞 时长"`
- airport ↔ city: `"<机场> 到 市区 怎么走 时间 价格"` (机场快线/大巴/打车)

**Flights — MANDATORY browser price check (机票必须用浏览器实查多平台).** web_search prices for flights
are stale/indicative; for every air leg you must read **live** fares in a browser. Procedure:

1. **First pass (web_search):** identify the target flight(s) — date, flight number, rough range.
2. **Browser pass (required):** with whichever browser tool is connected — **Claude in Chrome**,
   **Windows-MCP**, or **Desktop Commander** — open each platform's results page for that flight/date
   and **read** the fare:
   - 国内（**2026-06 实测平台真值表，省时间，别去碰已废的**）:
     - ✅ **携程** (`flights.ctrip.com` / `hotels.ctrip.com`) — 机票酒店免登录可读，台面价为裸价。
     - ✅ **飞猪** — 可用；常要淘宝登录 → 走登录墙协议（停在登录页、攒批问用户）。
     - ✅ **航司官网**（**必查**，东航/国航/南航实测可查价，吉祥/春秋等多数也可）— 有优惠券时可能比 OTA 低，
       且官网能读到**含税总价**（见下条）。
     - ✅ **高德地图** — 查不了酒店价格，但 **POI 评价真实可靠**（可作酒店评论信源），且路线规划给出
       **打车费/时长估算**（市内交通数字必须从这里来，不许拍脑袋）。
     - ❌ 已废，不要再查：**去哪儿**（机票+酒店桌面端均已下线）、**美团**（web 403）、**同程/艺龙**（基本残废）、
       **华住会官网**（查不到价）。
   - 国际: **Google Flights**、**Skyscanner**、航司官网 — these need no login, so prefer them and they
     rarely hit a wall.

   **燃油附加费 + 机场建设费（国内机票绝不可漏）：** 所有平台列表页显示的都是**裸票价**，不含
   燃油附加费与机建费。预算表必须用**含税总价** — 在航司官网或平台的价格明细里读出实际税费；读不到就在
   票价旁明确标注「票面价 · 燃油/机建另计，以出票页为准」，**绝不能自己编一个税费数**。
3. Record each `platform → price` **with the exact query time**, put them in `.price-compare` (cheapest
   tagged `class="cheapest"`), and set `.tr-price` to "最低 ¥X".

**Login walls — defer and BATCH (don't pause per-platform):**
- *You* never enter passwords, never read/solve/bypass a captcha/验证码, never click 下单/支付.
- When a platform hits a **login/captcha wall, don't stop and wait there.** Read whatever shows without
  logging in (e.g. its price-calendar lowest), leave the tab open and **navigate it to its login page**
  so it's ready, add it to a **needs-login list**, and **move on** to the next platform. Query all the
  login-free / already-open ones first.
- **After all platforms are queried**, if any need login, prompt the user **once** with the whole list:
  *"这几个要登录才能看完整价：去哪儿、飞猪……我已把每个标签页停在登录页了。请你一次性全部登录（我不替你输密码/过
  验证码），都登好告诉我，我再回去逐个读价。"* **Wait** for one confirmation, then revisit each walled tab
  and **read its now-accessible fare**. The user logs in once for all, not once per site.
- **Fall back per-platform** only for sites with no browser / that the user skips: use web_search ranges
  **labeled** "web_search 估价 · 未浏览器核实，请在购票平台确认" — never as verified; keep the live-read
  platforms as the real comparison.

Trains are exempt: a 12306/web_search fare is the source of truth.

**Weather & season:**
- `"<目的地> <月份> 天气 气温 降水"` · `"<destination> weather in <month>"`
- within ~2 weeks: `"<目的地> 未来一周 天气预报"` · `"<destination> 7 day forecast"`
- `"<目的地> <日期> 节庆 活动"` · `"<destination> events <dates>"`

**Per-place facts (verify each):**
- `"<景点> 开放时间 门票 闭馆日"` · `"<attraction> opening hours ticket price"`
- `"<景点> 需要预约 吗 官网 购票"` (timed-entry / 预约 / sells out)
- `"<景点> 经纬度"` or `"<place> latitude longitude"` → for the map's `lat`/`lng`
- `"<餐厅/区域> 营业时间 人均 推荐"` for meal stops

**Tips & avoid-traps:**
- `"<目的地> 避雷 坑 攻略"` · `"<destination> tourist traps avoid"` (corroborate before repeating —
  one ranty post isn't proof; look for repeated, specific complaints).

Capture for each place: name, address/area, **opening hours + closing day**, ticket price, why-go,
one practical tip, and `lat`/`lng`. If a field is unverifiable, record it as such and surface that in
the HTML rather than guessing.

---

## 2. Browser automation — only when search isn't enough

Use **Claude in Chrome** or **Windows-MCP** (whichever is installed) **only** to read live
availability / exact fares on 携程 / 飞猪 / 航司官网 / 12306. It is a read-only lookup, not a booking flow.

**Stop-and-hand-back triggers (do not cross these):**
- Login / account / password prompt → stop.
- CAPTCHA / 验证码 / 滑块 / 人机验证 → stop (never solve or bypass).
- Any "下单 / 提交订单 / 支付 / 立即预订" step → stop.

When you stop, give the user: the exact query URL, the date/route you searched, and the options you
already read (times, prices, train/flight numbers). They complete the booking. Put a booking link in
the transport card so they can pick up where you left off.

---

## 2.5 Hotels — vet the reviews, prefer chains, compare prices

Pick **≥3 hotel options** near the itinerary's clusters / transit and matching the user's 住宿位置偏好.
Selecting one is the same discipline as flights — **research, don't trust the listing; compare across
platforms; never book.**

**Read the review section, not the marketing blurb (the decisive step).** A polished listing and a high
headline number prove nothing. Open the actual reviews on 携程 / **高德地图**（POI 评价真实度高，可靠信源）/
大众点评 / 小红书 / Google / Booking and **sort to recent + lowest** so you read fresh and negative ones, then judge whether the
review area looks **normal**:

| Signal | Healthy (pick) | Suspicious (avoid / warn) |
|---|---|---|
| Volume & recency | many reviews, some in the last weeks | few, or all stale/old |
| Score shape | believable mix, mostly good | **100% 5★**, or score clashes with the written complaints |
| Specificity | concrete (隔音/早餐/前台/床/水压) | generic, dateless, copy-paste praise (水军 tell) |
| Negatives | minor/manageable | **recurring serious**: 卫生差/有虫/隔音/不安全/偷换房型/强制消费 |
| Cross-platform | consistent across sites | one glows, others warn → **trust the warnings** |

If the same serious complaint repeats across recent reviews, **drop the hotel** no matter how nice the
photos are.

**Prefer chains (连锁) when they fit — especially 银发/亲子** (consistent cleanliness, standards, easy
recourse): **华住会** (汉庭 / 全季 / 桔子 / 星程 / 宜必思 / 美居), **锦江** (锦江之星 / 7天 / 维也纳), **首旅
如家** (如家 / 和颐). A chain is **not an auto-pick** — a branch with bad recent reviews is still out
(**reviews override the brand**). Boutique/民宿 is fine if its reviews are strong, specific, authentic,
and it suits the trip — flag the higher variance.

**Multi-platform price (per night) — reuse the flight flow exactly.** Browser-check the same room/date on
**携程 + 飞猪** (+ Booking/Agoda international)，评价交叉看**高德**。**不要默认「集团 App 会员价更低」**——
实测华住会企业铂金会员价也未必低于携程，且华住会官网根本查不到价；会员价只有真读到了才能写。Cheapest
tagged, query time noted, `.price-compare` block. **Same defer-and-
batch login handling and query-only prohibitions as §1 flights** — you never log in / solve captchas /
book. Search shapes: `"<酒店名> 大众点评 评价"`, `"<酒店名> 携程 价格 <日期>"`, `"<品牌> <区域> 店 怎么样 测评"`.

---

## 3. Time-budget rules of thumb

Honest time accounting is what makes a plan usable. Rough stay durations (adjust to interest level):

| Stop type | Typical stay |
|---|---|
| 大型博物馆 / 美术馆 | 2–3 h |
| 地标 / 寺庙 / 广场 | 45–90 min |
| 观景台 / 塔 | 45–60 min |
| 公园 / 古镇老街 漫步 | 1.5–3 h |
| 主题乐园 | 大半天–整天 |
| 正餐 | 60–90 min；排队店 +30–45 min |
| 咖啡 / 小吃歇脚 | 30 min |

Add **point-to-point transit** between stops — **taxi cost/time and driving distance come from 高德
路线规划, not from your head**; metro hops are often 20–40 min door-to-door once you count walking +
waiting — **plus a 15–20 min buffer** per transition.
A day that looks full on paper with zero buffer will run 1–2 hours late by afternoon — pad it.

**Commute annotation + steps.** Record each inter-stop hop as **mode + distance + time** and put it in
the `.transit` connector between POI cards. Walking pace ≈ **70–80 m/min** (slower for 银发/亲子). Sum
the day's walking distance and convert to a **步数估算** (≈ **1,300 步/km**, e.g. 5 km ≈ 6,500 步) for the
day's overview line. Keep it grounded in the actual legs — don't print a step count you didn't derive.

**Pacing by profile:**
- 悠闲 / 银发 / 亲子（幼童）: 2–3 主要点/天, 早出晚归但中途留休息, 少爬楼梯, 午后留空档.
- 适中: 3 主要点/天 + 1 顺路小点.
- 暴走: 4 主要点/天, 早起, 接受长通勤 — only if the user chose this.

**Arrival/departure days are half-days.** Anchor them to the real flight/train times from Step 2 and
keep them light (drop bags, one nearby easy stop, good dinner).

---

## 4. Geographic clustering

- Plot every candidate stop (mentally or via the map) and **group by area**; assign each cluster to a
  day or half-day so the route reads as one smooth loop, not cross-town ping-pong.
- Order stops within a day to minimise backtracking; end near transit back to the hotel or near
  dinner.
- Use sunrise/sunset: sunrise spots first thing, sunset/night-view spots to close the day.
- Multi-city / day-trips: cluster the out-of-town trip on its own day, account for the round-trip
  transit time, and don't also pack the home city that day.

The embedded Leaflet map is your sanity check — if a day's polyline zig-zags across the whole city,
re-cluster.

---

## 5. Meals, constraints, energy, Plan B

- **Meals on the line**: pick lunch/dinner near the stop you'll physically be at when hungry; note
  hours and rough 人均. Respect dietary needs from Step 1 (清真 / 素食 / 过敏 / 忌口).
- **Hard constraints**: never schedule a stop on its closing day; honor 预约/timed-ticket windows;
  respect 无障碍 needs (elevators, fewer stairs, stroller/wheelchair friendly).
- **Energy curve**: hardest day in the middle; lighter on arrival/departure and after any long
  travel leg.
- **Plan B**: for each outdoor-heavy day give a concrete indoor alternative nearby (museum, mall,
  aquarium, covered market, café street) in a `weather` callout. Tie it to the actual forecast when
  you have one.

---

## 6. Map coordinates

Each map stop needs numeric `lat`/`lng` (decimal degrees, ~4 decimals). Prefer well-known/verified
coordinates; a **district or landmark** coordinate is a fine fallback when a precise one isn't
available — an approximate pin beats no pin. Do **not** fabricate precise-looking coordinates for a
place you couldn't locate; round to district level and say the pin is approximate if needed. Set
`TRIP.center` to the city center and `TRIP.zoom` to 10–12 for a single city.

---

## 7. Honesty & safety recap

- Query-only for tickets; never log in, never solve CAPTCHAs, never pay.
- Every hours/price/address/schedule is sourced or marked unverified — no invented facts.
- The plan is advisory: end the HTML with a reminder to re-confirm hours and prices before going, and
  to book anything marked `must` early.
