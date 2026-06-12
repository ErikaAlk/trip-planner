#!/usr/bin/env python3
r"""check_html.py — static sanity checks for a trip-planner HTML output.

Usage:
    python3 check_html.py <output>.html
    py       check_html.py <output>.html      # Windows

Checks (each FAIL must be fixed before presenting the file):
  1. <div> balance            open vs close, and exactly one .page wrapper
  2. Leaflet + map wiring      leaflet.js/.css CDN present, a <div id="map">,
                               a TRIP object, and an OSM tile URL
  3. Map coordinates           every stop in TRIP has numeric lat & lng
  4. No leftover KaTeX math    the template descends from study-notes; stray
                               $$...$$ / KaTeX CDN means math snuck in
  5. Self-contained           no http(s) <img src> (images must be base64);
                               only leaflet/openstreetmap may be remote

Exit code: 0 = clean, 1 = one or more FAILs.  Pure standard library.
"""
import re
import sys


def line_of(text, pos):
    return text[:pos].count("\n") + 1


def strip_non_markup(html):
    """Remove <style>, <script>, and <!-- --> regions so their contents (CSS
    comments that mention `<div ...>`, JS that builds a `<div>` string, etc.)
    don't pollute the markup-level <div> balance count."""
    html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.S | re.I)
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return html


def check_div_balance(html):
    markup = strip_non_markup(html)
    opens = len(re.findall(r"<div\b", markup))
    closes = len(re.findall(r"</div\s*>", markup))
    page = len(re.findall(r'<div\s+class="[^"]*\bpage\b', markup))
    return opens, closes, page


def check_leaflet(html):
    problems = []
    if "leaflet" not in html.lower():
        problems.append("Leaflet CDN not found (need leaflet.js + leaflet.css from unpkg/jsdelivr)")
    else:
        if not re.search(r"leaflet@[\d.]+/dist/leaflet\.js", html):
            problems.append("leaflet.js script tag not found")
        if not re.search(r"leaflet@[\d.]+/dist/leaflet\.css", html):
            problems.append("leaflet.css link tag not found")
    if not re.search(r'id\s*=\s*"map"', html):
        problems.append('no <div id="map"> container')
    if not re.search(r"\bvar\s+TRIP\s*=", html):
        problems.append("no `var TRIP = {...}` map-data object")
    if "tile.openstreetmap.org" not in html:
        problems.append("OSM tile URL (tile.openstreetmap.org) not found")
    return problems


# Pull out the TRIP = { ... }; object literal (best-effort brace matching).
def extract_trip(html):
    m = re.search(r"\bvar\s+TRIP\s*=\s*\{", html)
    if not m:
        return None
    i = m.end() - 1  # at the '{'
    depth, j = 0, i
    while j < len(html):
        c = html[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return html[i:j + 1]
        j += 1
    return None


def check_coords(html):
    """Every stop object that names a place should carry numeric lat & lng."""
    trip = extract_trip(html)
    problems = []
    if trip is None:
        return ["could not isolate the TRIP object to check coordinates"]
    stops = re.findall(r"\{[^{}]*\bname\s*:[^{}]*\}", trip)
    if not stops:
        problems.append("TRIP has no stop objects with a `name:` field")
        return problems
    for idx, s in enumerate(stops, 1):
        lat = re.search(r"\blat\s*:\s*(-?\d+(?:\.\d+)?)", s)
        lng = re.search(r"\blng\s*:\s*(-?\d+(?:\.\d+)?)", s)
        nm = re.search(r"name\s*:\s*['\"]([^'\"]*)", s)
        label = (nm.group(1) if nm else f"#{idx}")
        if not lat or not lng:
            problems.append(f"stop '{label}' is missing numeric lat/lng")
        else:
            la, lo = float(lat.group(1)), float(lng.group(1))
            if not (-90 <= la <= 90 and -180 <= lo <= 180):
                problems.append(f"stop '{label}' has out-of-range coords ({la}, {lo})")
    return problems


def check_no_katex(html):
    problems = []
    if "katex" in html.lower():
        problems.append("KaTeX reference found — remove it (trip-planner has no math)")
    # display-math delimiters that survived from the study-notes template
    dollars = [line_of(html, m.start()) for m in re.finditer(r"\$\$", html)]
    if dollars:
        problems.append(f"stray '$$' math delimiters at line(s) {', '.join(map(str, dollars[:20]))}")
    return problems


def check_self_contained(html):
    problems = []
    for m in re.finditer(r'<img\b[^>]*\bsrc\s*=\s*"(https?://[^"]+)"', html, re.I):
        problems.append(f"remote <img src> at line {line_of(html, m.start())}: "
                        f"{m.group(1)[:60]}… (inline as base64 instead)")
    return problems


def run(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        print(f"FAIL: file not found: {path}")
        return False

    fails = 0
    print(f"=== checking {path} ({len(html)} chars) ===")

    opens, closes, page = check_div_balance(html)
    if opens != closes:
        fails += 1
        print(f"[FAIL] <div> imbalance: {opens} '<div>' vs {closes} '</div>' (diff {opens - closes:+d})")
    else:
        print(f"[ok]  <div> balanced ({opens} open / {closes} close)")
    if page != 1:
        print(f"[warn] found {page} '.page' wrappers (expected exactly 1)")

    for label, probs in [
        ("Leaflet/map wiring", check_leaflet(html)),
        ("map coordinates", check_coords(html)),
        ("no leftover KaTeX", check_no_katex(html)),
        ("self-contained", check_self_contained(html)),
    ]:
        if probs:
            fails += 1
            print(f"[FAIL] {label}:")
            for p in probs[:30]:
                print(f"        - {p}")
            if len(probs) > 30:
                print(f"        … and {len(probs) - 30} more")
        else:
            print(f"[ok]  {label}")

    print()
    if fails:
        print(f"RESULT: {fails} FAIL-level check(s). Fix and re-run.")
        return False
    print("RESULT: all checks passed.")
    return True


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python3 check_html.py <output>.html")
    sys.exit(0 if run(sys.argv[1]) else 1)


if __name__ == "__main__":
    main()
