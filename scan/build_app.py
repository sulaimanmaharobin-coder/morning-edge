"""Build app.html: the Morning Edge app, one page with every morning feed.

Usage: python scan/build_app.py <site_dir> [jev_dir]
  site_dir  the built site (reads the newest edition, writes app.html)
  jev_dir   optional checkout of jev-trader's scan-reports branch
Feeds: the newest edition, scan/out/latest.json (pullback scan), crypto
watchlist setups and breakout labels (Crypto.com), and jev-trader's breakout
and watch levels. Holdings and paper balances are never read: this page is
public. A feed that fails is shown as unavailable, never guessed.
"""
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_feeds  # noqa: E402
import pullback_scan  # noqa: E402

CONFIG = os.path.join(HERE, "app_config.json")


def text(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def edition(site):
    names = sorted(f for f in os.listdir(site) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.html", f))
    if not names:
        return None
    page = open(os.path.join(site, names[-1]), encoding="utf-8").read()
    page = re.sub(r"<!-- pullback:start -->.*?<!-- pullback:end -->", "", page, flags=re.S)

    def first(pat, src=page):
        m = re.search(pat, src, re.S)
        return m.groups() if m else None

    lead = first(r'<h1><a href="([^"]+)"[^>]*>(.*?)</a></h1>')
    briefs = []
    for art in re.findall(r'<article class="brief">(.*?)</article>', page, re.S):
        h = first(r'<h3><a href="([^"]+)"[^>]*>(.*?)</a></h3>', art)
        if h:
            briefs.append(dict(url=h[0], title=text(h[1]),
                               body=text((first(r"<h3>.*?</h3>\s*<p>(.*?)</p>", art) or [""])[0]),
                               why=text((first(r'<p class="why">(.*?)</p>', art) or [""])[0]).replace("Why it matters", "", 1).strip()))
    reads = []
    for art in re.findall(r'<article class="read">(.*?)</article>', page, re.S):
        h = first(r'<h4><a href="([^"]+)"[^>]*>(.*?)</a></h4>', art)
        if h:
            reads.append(dict(url=h[0], title=text(h[1]), src=text((first(r'<p class="src">(.*?)</p>', art) or [""])[0]),
                              why=text((first(r'<p class="why">(.*?)</p>', art) or [""])[0])))
    return dict(
        date=names[-1][:10], file=names[-1],
        lead=dict(url=lead[0], title=text(lead[1])) if lead else None,
        dek=text((first(r'<p class="dek">(.*?)</p>') or [""])[0]),
        byline=text((first(r'<div class="byline">(.*?)</div>') or [""])[0]),
        why=text((first(r'<div class="why-box"><b>.*?</b>(.*?)</div>') or [""])[0]),
        briefs=briefs, reads=reads)


def jev(jev_dir):
    if not jev_dir or not os.path.isdir(os.path.join(jev_dir, "state")):
        return None

    def load(name):
        try:
            return json.load(open(os.path.join(jev_dir, "state", name)))
        except Exception:
            return None

    def day(n):
        return (date(1970, 1, 1) + timedelta(days=n)).isoformat() if isinstance(n, int) else None

    out = {}
    for sleeve in ("prebreak", "growth"):
        b, w = load(f"{sleeve}-breakouts.json") or {}, load(f"{sleeve}-watch.json") or {}
        out[sleeve] = dict(
            scanned=(datetime.fromtimestamp(b["made_ms"] / 1000, timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M SGT") if b.get("made_ms") else None,
            bar_day=day(b.get("bar_day")),
            breakouts=[dict(ticker=x["ticker"], close=x["close"], level=x["level"], vol_ratio=x.get("vol_ratio"),
                            rev_yoy=x.get("rev_yoy"), day=day(x.get("day"))) for x in b.get("breakouts", [])],
            watch=[dict(ticker=k, level=v.get("level"), rev_yoy=v.get("rev_yoy"))
                   for k, v in sorted((w.get("names") or {}).items())])
    reports = sorted(f for f in os.listdir(os.path.join(jev_dir, "stock-scan")) if f.endswith(".md")) if os.path.isdir(
        os.path.join(jev_dir, "stock-scan")) else []
    out["report_date"] = reports[-1][:10] if reports else None
    return out


def buy_zone(rows, ranked):
    """Every buy-zone name, crypto and stocks: ranked pre-breakouts first, then the rest
    by distance to the 20-day high. Compact fields only."""
    order = {r["sym"]: i for i, r in enumerate(ranked)}
    keep = ("sym", "kind", "close", "d20", "rsi", "e50", "stop_pct", "stop_atr", "to_hi", "pre_breakout")
    buys = [r for r in rows if r["status"] == "buy"]
    buys.sort(key=lambda r: (r["sym"] not in order, order.get(r["sym"], 0), r["to_hi"]))
    out = []
    for r in buys:
        row = {k: r.get(k) for k in keep}
        row["ranked"] = r["sym"] in order
        out.append(row)
    return out


def main():
    site = sys.argv[1]
    jev_dir = sys.argv[2] if len(sys.argv) > 2 else None
    cfg = json.load(open(CONFIG)) if os.path.exists(CONFIG) else {}
    sgt = datetime.now(timezone.utc) + timedelta(hours=8)
    data = dict(built=sgt.strftime("%Y-%m-%d %H:%M"), work_url=cfg.get("work_url"), errors={})
    try:
        data["edition"] = edition(site)
    except Exception as e:
        data["edition"], data["errors"]["edition"] = None, type(e).__name__
    try:
        pb = json.load(open(os.path.join(HERE, "out", "latest.json")))
        pre = [r for r in pb["rows"] if r.get("pre_breakout")]
        ranked = sorted((r for r in pre if (r.get("stop_atr") or 0) >= pullback_scan.MIN_STOP_ATR),
                        key=lambda r: r["stop_atr"])
        data["pullback"] = dict(scanned=pb.get("scanned_sgt"), notes=pb.get("notes", []), total=len(pre),
                                noise=len(pre) - len(ranked), buy_zone=sum(r["status"] == "buy" for r in pb["rows"]),
                                rows=ranked[:pullback_scan.TOP_N], all=buy_zone(pb["rows"], ranked))
    except Exception as e:
        data["pullback"], data["errors"]["pullback"] = None, type(e).__name__
    try:
        rows, failed = crypto_feeds.watchlist_setups()
        data["setups"] = dict(rows=rows, failed=failed)
    except Exception as e:
        data["setups"], data["errors"]["setups"] = None, type(e).__name__
    try:
        rows, skipped = crypto_feeds.breakout_scan()
        data["breakouts"] = dict(rows=rows, skipped=skipped)
    except Exception as e:
        data["breakouts"], data["errors"]["breakouts"] = None, type(e).__name__
    try:
        data["jev"] = jev(jev_dir)
    except Exception as e:
        data["jev"], data["errors"]["jev"] = None, type(e).__name__
    tpl = open(os.path.join(HERE, "app_template.html"), encoding="utf-8").read()
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    open(os.path.join(site, "app.html"), "w", encoding="utf-8").write(tpl.replace("__APP_DATA__", blob))
    print("app.html built;", "errors:", data["errors"] or "none")
    for r in (data.get("pullback") or {}).get("all", []):  # readable in the Actions log
        print(f"buy-zone {r['kind']:6} {r['sym']:8} d20 {r['d20']:+5.1f}% rsi {r['rsi']:4.1f} "
              f"stop {r['stop_pct']:4.1f}% atr {r['stop_atr'] if r['stop_atr'] is not None else 'n/a'} "
              f"to-high {r['to_hi']:5.1f}%{' PRE' if r['pre_breakout'] else ''}")


if __name__ == "__main__":
    main()
