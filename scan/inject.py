"""Insert scan/out/section.html into the built site, just above the footer.

Usage: python scan/inject.py <site_dir>
Touches index.html and the newest dated edition (YYYY-MM-DD.html). Any earlier
pullback block in those pages is replaced, so re-runs are safe.
"""
import os
import re
import sys

site = sys.argv[1]
src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "section.html")
if not os.path.exists(src):
    sys.exit("no section.html, nothing injected")
section = open(src).read()
editions = sorted(f for f in os.listdir(site) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.html", f))
targets = ["index.html"] + editions[-1:]
block = re.compile(r"<!-- pullback:start -->.*?<!-- pullback:end -->\n?", re.S)
for name in targets:
    path = os.path.join(site, name)
    if not os.path.exists(path):
        continue
    page = block.sub("", open(path).read())
    if "<footer" not in page:
        print(f"{name}: no <footer>, skipped")
        continue
    page = page.replace("<footer", section + "\n<footer", 1)
    open(path, "w").write(page)
    print(f"{name}: injected")
