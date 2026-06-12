<div align="center">

# trip-planner | 查证型行程页

> *「网上抄来的攻略,会把你送到闭馆的大门口。」*

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-trip--planner-blueviolet)](SKILL.md)
[![Runtime](https://img.shields.io/badge/Claude%20Code-ready-blue)](https://claude.com/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**把"网上抄来的攻略"变成"查证过的行程页"——单文件 HTML,带活地图、实价比价和不撒谎的营业时间。**

[看效果](#效果示例) · [安装](#快速开始) · [触发方式](#触发方式) · [和同类有什么不同](#它和同类有什么不同) · [安全边界](#安全边界)

</div>

---

![成都4日游行程页首屏:主题化头部 + 行程概览 + Leaflet 地图](assets/hero-desktop.png)
<sub>真实运行产物(成都 4 日银发亲子行程),非设计稿。完整文件见 [examples/成都4日游行程.html](examples/成都4日游行程.html)。</sub>

---

## 它解决什么问题

你让 AI 排过行程吗?它会热情地给你一篇小作文:景点是真的,营业时间是编的;路线在地图上画出来是个"米"字;机票价格停留在它的训练数据里;酒店推荐抄的是商家简介,不是住客差评。

这个 skill 换了一个思路:**行程不是写出来的,是查证出来的。** 它跑一个四段工作流——先采需求、再检索交通/天气/开放时间、然后逐项核对(闭馆日、赶车缓冲、日落时间),最后才组装页面。每个数字要么来自当场检索或浏览器实价,要么老老实实标「以官网为准」。机票和酒店价格走浏览器多平台实查(只读,绝不下单);酒店看的是**最近的差评**,不是头图和评分。

产出是**一个自包含 HTML 文件**:发给同行人就能用,旅途中手机离线打开,勾掉的清单项都记得住。

## 效果示例

**输入**(一句话,真实 eval prompt):

```text
下个月中旬带爸妈去成都玩4天,从上海出发,预算中等,想看大熊猫、吃地道川菜,
老人家走不动太多路,节奏悠闲点,帮我做个行程。
```

**输出**(同一次运行的三个截面):

| 逐日时间线 + 交通段卡 | 住宿备选(评论体检) | 手机端 |
|---|---|---|
| ![timeline](assets/timeline-desktop.png) | ![hotels](assets/hotels-desktop.png) | ![mobile](assets/mobile.png) |

注意截图里的细节:航班价格标着「web_search 估价 · 未浏览器核实(查询于 2026-06-12)」——没核实的数字**长得就和核实过的不一样**;住宿卡下面那条「评论压过品牌」的 callout,是因为某连锁分店近期差评分化而被换掉。

**对照实验**(2 个中文用例,同 prompt 跑 with/without skill,[完整数据](evals/benchmark.md)):

| 配置 | 自动检查 | HTML 校验 | 地图 | 主题头 | POI 四字段卡 |
|---|---|---|---|---|---|
| **with skill** | **10/10 ×2** | 全过 | ✅ | ✅ | ✅ |
| baseline(无 skill) | 5/10 ×2 | FAIL ×2 | ❌ | ❌ | ❌ |

成本如实说:with-skill 约 2× tokens 和耗时(~10 万 tokens / 7–8 分钟)——这是真检索 + 完整结构化构建的价格。

## 快速开始

```bash
git clone https://github.com/Eric6286/trip-planner ~/.claude/skills/trip-planner
```

装完对 Claude Code 说(可直接复制):

```text
国庆想去西安玩4天,从北京出发,帮我做个行程
```

无前置依赖、零 API key:地图用 Leaflet + OpenStreetMap(免 key),检索用 Agent 自带的 web search,浏览器比价在有 Chrome 连接时自动启用、没有就降级为标注过的估价。

## 触发方式

- 帮我规划行程 / 做个旅行计划 / 帮我排个行程
- 6月去东京玩5天 / 国庆想去成都4天
- 下周末杭州两日游怎么安排?
- 带爸妈去厦门,节奏慢一点,帮我做攻略
- Plan a 5-day Tokyo itinerary, flying from Shanghai
- 9月23到26号去西安,顺便看下北京出发的高铁几点有车

## 它会交付什么

一个自包含 HTML 行程页,包含:主题化渐变头部(按目的地配色)、内嵌 Leaflet 地图(逐日编号 pin + 路线)、逐日 POI 时间线卡(到达时间/停留/票价/营业时间)、点间通勤连接器(步行/地铁/打车 + 距离 + 时间)、每日花费与步数估算、交通段卡(航班/车次 + 多平台比价)、**≥3 张住宿备选卡(评论体检 + 比价,用户没提酒店也会有)**、按天小计的预算表、localStorage 出发前清单、雨天 Plan B,以及 注意/必订/避雷 callout。

## 它和同类有什么不同

| 维度 | 同类常见做法 | 本 skill |
|---|---|---|
| 地图 | 无地图,或跳转链接([ycyliu](https://github.com/ycyliu/travel-planner-skill)、[SunDaysketch](https://github.com/SunDaysketch/travel-planner-skill)),或要 API key + 本地服务器([sucr233](https://github.com/sucr233/travel_planner_skills)) | 内嵌 Leaflet + OSM,免 key,单文件离线可看 |
| 价格数据 | 硬编码在 skill 里(会过期),或模型记忆 | 浏览器多平台实查;查不到就标「以官网为准」,不编 |
| 酒店推荐 | 抄商家简介和评分 | 读最近差评做「评论体检」,评论压过品牌 |
| 预订 | 部分同类可直接下单 | **只查询,永不下单/登录/过验证码**——预订永远是你自己的动作 |
| 输出验证 | 无 | 静态校验器把关:地图坐标、组件齐全、自包含,缺住宿卡直接 FAIL |

## 安全边界

- **只读不订**:永不下单、付款、占座;预订链接给你,动作你来做。
- **永不碰你的凭据**:不输密码、不解验证码/滑块。遇登录墙会把标签页停在登录页、攒成一批请你登录一次,然后只做"读价"。
- **不编数字**:营业时间、票价、班次,核实不了就明确标注,绝不填一个看起来合理的数。
- 不删改你的文件,只在你指定的目录写一个 HTML。

## 文件结构

```
trip-planner/
├── SKILL.md                        # 工作流:需求采集 → 交通 → 天气/真实数据 → 编排 → 住宿 → 输出
├── references/
│   ├── design-system.md            # HTML 输出规范(脚手架/CSS/JS + 全部组件)
│   └── research-playbook.md        # 检索/浏览器比价/选酒店方法
├── scripts/
│   ├── check_html.py               # 输出静态校验(地图/坐标/住宿/预算/清单/自包含)
│   └── make_showcase.sh            # 从真实产物重新生成 README 截图(可复现)
├── evals/
│   ├── evals.json                  # 2 个标准测试 prompt + 期望输出
│   └── benchmark.md                # with/without skill 对照实验数据
├── examples/成都4日游行程.html      # 一次真实运行的完整产物
└── assets/                         # README 截图(全部出自真实产物)
```

## 验证与测试

拿 [evals/evals.json](evals/evals.json) 里的 prompt 跑一遍,合格的产物应当一次通过:

```bash
py scripts/check_html.py 成都4日游行程.html   # Windows
python3 scripts/check_html.py <输出>.html      # macOS/Linux
```

校验器检查:`<div>` 平衡、Leaflet 接线、每个地图点的数字坐标、无模板残留、自包含、以及旅行组件是否真实落地(≥3 住宿卡/预算表/清单)。对照实验方法与数据见 [evals/benchmark.md](evals/benchmark.md)。

## 更新记录

- **2026-06-12 · v0.2** — 活体审计发现 4 次真实运行里住宿备选全部静默脱落、而校验器对此失明。修法:Step 5 改为不可跳过(已订住宿走 `data-hotels="user-booked"` 显式出口),校验器新增旅行组件检查(历史产物回放 4/4 翻转、零误报),并用一次完整 eval 重跑验证修复(一次过,3 张住宿卡落地)。
- **2026-06-12 · v0.1** — 冻结基线:六步工作流 + 设计系统 + 静态校验器 + 2 用例 benchmark。

## License

[MIT](LICENSE)

---

<div align="center">

*查过的才叫行程,没查过的叫愿望清单。*

</div>
