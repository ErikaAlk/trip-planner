#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_demo_gif.py — build the README demo GIF by smooth-scrolling a REAL output page.

Renders examples/<trip>.html full-page in headless Chrome (so the Leaflet/OSM map
tiles load), then slides a viewport-height window down the tall capture to fake a
smooth auto-scroll, and writes an optimized animated GIF. Reproducible — the GIF is
always regenerated from a real artifact, never hand-mocked.

Usage:  py scripts/make_demo_gif.py [examples/成都4日游行程.html] [assets/demo.gif]
"""
import os
import subprocess
import sys

from PIL import Image

HTML = sys.argv[1] if len(sys.argv) > 1 else "examples/成都4日游行程.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else "assets/demo.gif"
RENDER_W = 1000          # capture width (crisp desktop layout)
FRAME_W = 720            # downscaled GIF width
VIEW_H = 600             # viewport-window height (in render px) per frame
STEP = 140              # scroll step per frame (render px) — smaller = smoother
MAX_SCROLL = 5600        # cap the demo at the most compelling slice (hero→map→hotels→day1)
HOLD_TOP = 6            # repeat first frame N times (linger on the hero)
HOLD_END = 7           # repeat last frame N times
FRAME_MS = 110          # per-frame duration
COLORS = 96            # GIF palette size

CHROME = next((p for p in [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
] if os.path.exists(p)), None)


def render_fullpage(html, png):
    url = "file:///" + os.path.abspath(html).replace("\\", "/")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--virtual-time-budget=12000",
                    f"--window-size={RENDER_W},16000", f"--screenshot={os.path.abspath(png)}", url],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def content_bottom(im):
    """Find where the page content ends. Walk top→down; the page ends at the start
    of the first long run of near-uniform background rows. Exclude the right ~90px
    (a position:fixed floating nav button lives there and would defeat a bottom-up
    scan) and the left ~12px."""
    g = im.convert("L")
    px = g.load()
    w, h = g.size
    x0, x1 = 12, w - 90
    blank_run, run_start = 0, h
    for y in range(0, h, 2):
        row = [px[x, y] for x in range(x0, x1, 19)]
        is_blank = (max(row) - min(row)) < 18
        if is_blank:
            if blank_run == 0:
                run_start = y
            blank_run += 2
            if blank_run >= 160:          # long blank stretch → content ended at run_start
                return max(400, run_start + 24)
        else:
            blank_run = 0
    return h


def main():
    if CHROME is None:
        sys.exit("no Chrome/Edge found")
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    tmp = OUT + ".full.png"
    render_fullpage(HTML, tmp)
    im = Image.open(tmp).convert("RGB")
    H = min(content_bottom(im), MAX_SCROLL)
    im = im.crop((0, 0, RENDER_W, H))

    frames, y = [], 0
    last = max(0, H - VIEW_H)
    while y < last:
        win = im.crop((0, y, RENDER_W, y + VIEW_H))
        win = win.resize((FRAME_W, int(VIEW_H * FRAME_W / RENDER_W)), Image.LANCZOS)
        frames.append(win.convert("P", palette=Image.ADAPTIVE, colors=COLORS))
        y += STEP
    tail = im.crop((0, last, RENDER_W, H)).resize(
        (FRAME_W, int((H - last) * FRAME_W / RENDER_W)), Image.LANCZOS).convert(
        "P", palette=Image.ADAPTIVE, colors=COLORS)
    frames.append(tail)

    seq = frames[:1] * HOLD_TOP + frames + frames[-1:] * HOLD_END
    seq[0].save(OUT, save_all=True, append_images=seq[1:], loop=0,
                duration=FRAME_MS, optimize=True, disposal=2)
    os.remove(tmp)
    kb = os.path.getsize(OUT) // 1024
    print(f"wrote {OUT}  ({len(seq)} frames, {kb} KB, content height {H}px)")


if __name__ == "__main__":
    main()
