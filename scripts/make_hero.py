#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_hero.py — composite the README hero banner from REAL screenshots.

Dark tech-travel background + glow, real desktop screenshot in a browser frame
(center), real mobile screenshot in a phone frame (right, overlapping), tagline
and selling-point pills on the left. Rendered with headless Chrome so the real
PNGs are pixel-accurate and the Chinese copy is crisp (unlike text-to-image).

Usage:  py scripts/make_hero.py
Output: assets/hero.png  (1280x640 @2x)
"""
import base64
import os
import subprocess
import sys

CHROME = next((p for p in [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
] if os.path.exists(p)), None)


def b64(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def b64_img(im):
    import io
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def render_full(html_path, w):
    """Render a full-page capture of the example at width w; return PIL image."""
    from PIL import Image
    cap = "assets/_full_tmp.png"
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--virtual-time-budget=12000",
                    f"--window-size={w},16000", f"--screenshot={os.path.abspath(cap)}", url],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    im = Image.open(cap).convert("RGB")
    os.remove(cap)
    return im


def map_band(im, y_from=420):
    """Find the embedded map (the brightest tall light region — OSM tiles)."""
    g = im.convert("L")
    px = g.load()
    w, h = g.size
    rows = []
    for y in range(y_from, h, 8):
        v = sum(px[x, y] for x in range(80, w - 80, 30)) / len(range(80, w - 80, 30))
        rows.append((y, v))
    bright = [y for y, v in rows if v > 110]
    if not bright:
        return None
    return min(bright), max(bright) + 8


def device_shot(html_path, w, header_h, map_h):
    """Compose header band + map band into one punchy device screenshot."""
    from PIL import Image
    im = render_full(html_path, w)
    header = im.crop((0, 0, w, header_h))
    mb = map_band(im)
    if mb:
        top = min(mb[0], im.height - 1)
        bot = min(top + map_h, im.height)
        mp = im.crop((0, top, w, bot))
    else:
        mp = im.crop((0, header_h, w, header_h + map_h))
    out = Image.new("RGB", (w, header.height + mp.height), "#0b111c")
    out.paste(header, (0, 0))
    out.paste(mp, (0, header.height))
    return out


HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1280px;height:640px;overflow:hidden;font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif}}
.stage{{position:relative;width:1280px;height:640px;
  background:radial-gradient(125% 150% at 16% 8%,#1b2748 0%,#0e1524 46%,#090d16 100%);overflow:hidden}}
.glow{{position:absolute;border-radius:50%;filter:blur(90px);opacity:.55;pointer-events:none}}
.g-teal{{width:560px;height:560px;left:-160px;top:-120px;background:#15c2a8}}
.g-amber{{width:620px;height:620px;left:760px;top:150px;background:#e8902f;opacity:.42}}
.g-cyan{{width:420px;height:420px;left:430px;top:360px;background:#2b6cd6;opacity:.35}}
.deco{{position:absolute;inset:0;opacity:.5;pointer-events:none}}
.vig{{position:absolute;inset:0;box-shadow:inset 0 0 220px 60px rgba(5,8,14,.9);pointer-events:none}}

/* ── left copy ── */
.copy{{position:absolute;left:66px;top:0;height:640px;width:430px;display:flex;flex-direction:column;
  justify-content:center;z-index:5}}
.eyebrow{{display:inline-flex;align-items:center;gap:8px;color:#34e0c4;font-size:13px;font-weight:700;
  letter-spacing:.16em;margin-bottom:18px}}
.eyebrow b{{width:18px;height:2px;background:#34e0c4;display:inline-block}}
h1{{font-size:42px;line-height:1.18;font-weight:800;color:#f4f7fd;letter-spacing:-.5px}}
h1 .hl{{background:linear-gradient(92deg,#34e0c4,#7fe3ff);-webkit-background-clip:text;background-clip:text;color:transparent}}
.sub{{margin-top:16px;font-size:15.5px;line-height:1.7;color:#9fb0cc;max-width:380px}}
.pills{{margin-top:26px;display:flex;flex-wrap:wrap;gap:9px;max-width:400px}}
.pill{{display:inline-flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:#d7e2f4;
  background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);border-radius:20px;padding:6px 13px;
  backdrop-filter:blur(4px)}}
.dot{{width:7px;height:7px;border-radius:50%}}

/* ── devices ── */
.devices{{position:absolute;right:0;top:0;width:820px;height:640px;perspective:1500px;z-index:4}}
.browser{{position:absolute;left:80px;top:96px;width:600px;height:392px;border-radius:13px;overflow:hidden;
  background:#0b111c;border:1px solid rgba(255,255,255,.10);
  box-shadow:0 40px 80px -24px rgba(0,0,0,.7),0 0 70px -10px rgba(21,194,168,.45),0 0 0 1px rgba(21,194,168,.08);
  transform:rotateY(-13deg) rotateX(3deg)}}
.bar{{height:32px;background:#10182600;background:linear-gradient(#141d2e,#0e1521);display:flex;align-items:center;
  gap:7px;padding:0 13px;border-bottom:1px solid rgba(255,255,255,.06)}}
.tl{{width:11px;height:11px;border-radius:50%}}
.url{{margin-left:14px;flex:1;height:18px;border-radius:9px;background:rgba(255,255,255,.06);
  display:flex;align-items:center;padding:0 10px;font-size:11px;color:#7e8eaa;max-width:260px}}
.browser .shot{{width:100%;height:360px;object-fit:cover;object-position:top}}
.phone{{position:absolute;left:600px;top:150px;width:218px;height:446px;border-radius:30px;
  background:#070b12;border:1px solid rgba(255,255,255,.14);padding:9px 8px;
  box-shadow:0 44px 70px -18px rgba(0,0,0,.78),0 0 60px -6px rgba(232,144,47,.5);
  transform:rotateY(-13deg);z-index:6}}
.notch{{position:absolute;left:50%;top:13px;transform:translateX(-50%);width:62px;height:6px;border-radius:6px;
  background:rgba(255,255,255,.18);z-index:2}}
.phone .shot{{width:100%;height:100%;object-fit:cover;object-position:top;border-radius:23px;display:block}}

.foot{{position:absolute;left:66px;bottom:30px;font-size:12.5px;color:#5d6c87;letter-spacing:.04em;z-index:5}}
.foot b{{color:#8fa0bd;font-weight:600}}
</style></head><body>
<div class="stage">
  <div class="glow g-teal"></div><div class="glow g-amber"></div><div class="glow g-cyan"></div>
  <svg class="deco" viewBox="0 0 1280 640" fill="none">
    <g stroke="#3ad6c0" stroke-width="1.2" stroke-dasharray="3 7" opacity="0.5">
      <path d="M120 470 C 360 300, 720 250, 1180 120"/>
      <path d="M40 250 C 320 200, 560 420, 1080 470"/>
    </g>
    <g fill="#6fe9d6" opacity="0.7">
      <circle cx="120" cy="470" r="4"/><circle cx="1180" cy="120" r="4"/>
      <circle cx="1080" cy="470" r="3.5"/><circle cx="40" cy="250" r="3.5"/>
    </g>
    <g fill="#ffffff" opacity="0.35">
      <circle cx="300" cy="90" r="1.3"/><circle cx="540" cy="60" r="1"/><circle cx="900" cy="540" r="1.2"/>
      <circle cx="1140" cy="360" r="1"/><circle cx="700" cy="120" r="1"/><circle cx="220" cy="560" r="1.1"/>
    </g>
  </svg>

  <div class="copy">
    <span class="eyebrow"><b></b>TRIP-PLANNER · CLAUDE CODE SKILL</span>
    <h1>把"抄来的攻略"<br>变成<span class="hl">查证过的行程页</span></h1>
    <p class="sub">网上抄来的攻略,会把你送到闭馆的大门口。<br>这个 skill 跑遍携程/飞猪/高德实查,查不到就标注、绝不编造。</p>
    <div class="pills">
      <span class="pill"><span class="dot" style="background:#34e0c4"></span>内嵌活地图</span>
      <span class="pill"><span class="dot" style="background:#f5b14c"></span>实价比价</span>
      <span class="pill"><span class="dot" style="background:#7fe3ff"></span>查证不编造</span>
      <span class="pill"><span class="dot" style="background:#a78bfa"></span>手机也能看</span>
    </div>
  </div>

  <div class="devices">
    <div class="browser">
      <div class="bar">
        <span class="tl" style="background:#ff5f56"></span><span class="tl" style="background:#ffbd2e"></span>
        <span class="tl" style="background:#27c93f"></span>
        <span class="url">成都4日游行程.html · 单文件 · 离线可看</span>
      </div>
      <img class="shot" src="{desk}">
    </div>
    <div class="phone"><div class="notch"></div><img class="shot" src="{mob}"></div>
  </div>

  <div class="vig"></div>
  <div class="foot"><b>github.com/Eric6286/trip-planner</b> &nbsp;·&nbsp; 单文件 HTML · Leaflet 活地图 · 零 API key</div>
</div></body></html>"""


def main():
    if CHROME is None:
        sys.exit("no Chrome/Edge found")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(here)
    example = "examples/成都4日游行程.html"
    desk = b64_img(device_shot(example, 1280, header_h=372, map_h=470))   # header + live map
    html = HTML.format(desk=desk, mob=b64("assets/mobile.png"))
    tmp = "assets/_hero.html"
    open(tmp, "w", encoding="utf-8").write(html)
    url = "file:///" + os.path.abspath(tmp).replace("\\", "/")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=2", "--virtual-time-budget=8000",
                    "--window-size=1280,640", f"--screenshot={os.path.abspath('assets/hero.png')}", url],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.remove(tmp)
    from PIL import Image
    print("wrote assets/hero.png", Image.open("assets/hero.png").size,
          os.path.getsize("assets/hero.png") // 1024, "KB")


if __name__ == "__main__":
    main()
