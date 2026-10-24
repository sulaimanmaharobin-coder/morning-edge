"""Daily 20/50 EMA + RSI pullback scan for The Morning Edge.

Rules (from the "Trading pull backs, 20-50 EMA & RSI" chart):
  trend    20 EMA above 50 EMA, close above 50 EMA, 50 EMA rising over 5 bars
  entry    price touches the 20 EMA (a daily low within 0.5% of it in the
           last two bars) while RSI(14) is above 50
  exit     20 EMA closes below 50 EMA, or price closes below 50 EMA
Pre-breakout = buy zone with the stop (50 EMA) within 5% and price within
5% of its 20-day high.

Crypto: top 50 coins by Crypto.com 24h volume (public API, closed UTC bars).
Stocks: S&P 500 from Yahoo Finance daily bars.
Standard library only. Writes scan/out/section.html and scan/out/latest.json.
"""
import csv
import html
import io
import json
import math
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
UA = {"User-Agent": "Mozilla/5.0 (morning-edge pullback scan)"}
CDC = "https://api.crypto.com/exchange/v1/public/"
SP500_CSV = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=1y&interval=1d"
STABLE = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "PYUSD", "USDE", "USD1", "RLUSD",
          "USDS", "EURC", "USAT", "EUR", "GBP", "PAXG", "XAUT", "WBTC", "CBBTC", "WETH", "STETH"}
TOUCH = 0.005        # low within 0.5% of the 20 EMA counts as a touch
ZONE = (-1.5, 2.0)   # close vs 20 EMA, % (below 0 = needs a close back above)
WATCH_MAX = 3.0      # close up to 3% above the 20 EMA = waiting for a pullback
TOP_N = 15           # pre-breakout rows shown in the paper
MIN_STOP_ATR = 1.0   # stops closer than one day's ATR sit inside normal noise


def get_json(url, tries=3):
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(2 * (n + 1))


def ema(xs, n):
    k, out, e = 2 / (n + 1), [], None
    for i, x in enumerate(xs):
        if i < n - 1:
            out.append(None)
            continue
        e = sum(xs[:n]) / n if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def atr(hi, lo, c, n=14):
    """Wilder ATR of the last bar."""
    tr = [hi[0] - lo[0]] + [max(hi[i] - lo[i], abs(hi[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
                            for i in range(1, len(c))]
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a


def rsi(xs, n=14):
    out = [None] * len(xs)
    if len(xs) <= n:
        return out
    g = sum(max(xs[i] - xs[i - 1], 0) for i in range(1, n + 1)) / n
    l = sum(max(xs[i - 1] - xs[i], 0) for i in range(1, n + 1)) / n
    out[n] = 100 - 100 / (1 + g / l) if l else 100.0
    for i in range(n + 1, len(xs)):
        d = xs[i] - xs[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + g / l) if l else 100.0
    return out


def evaluate(sym, kind, bars):
    """bars: closed daily bars, oldest first, as (high, low, close)."""
    if len(bars) < 80:
        return None
    hi = [b[0] for b in bars]
    lo = [b[1] for b in bars]
    c = [b[2] for b in bars]
    e20, e50, r = ema(c, 20), ema(c, 50), rsi(c)
    i = len(c) - 1
    up = e20[i] > e50[i] and c[i] > e50[i] and e50[i] > e50[i - 5]
    d20 = (c[i] / e20[i] - 1) * 100
    touched = any(lo[j] <= e20[j] * (1 + TOUCH) and c[j] > e50[j] for j in (i, i - 1))
    if e20[i] <= e50[i] or c[i] <= e50[i]:
        status = "exit"            # the chart's exit condition is live
    elif not up or r[i] <= 50:
        status = "no"
    elif touched and ZONE[0] <= d20 <= ZONE[1]:
        status = "buy"
    elif 0 < d20 <= WATCH_MAX:
        status = "watch"
    else:
        status = "no"
    stop = (c[i] / e50[i] - 1) * 100
    a = atr(hi, lo, c)
    stop_atr = (c[i] - e50[i]) / a if a else None
    to_hi = (max(hi[i - 20:i + 1]) / c[i] - 1) * 100
    return dict(sym=sym, kind=kind, close=c[i], e20=e20[i], e50=e50[i], rsi=round(r[i], 1),
                d20=round(d20, 1), stop_pct=round(stop, 1),
                stop_atr=round(stop_atr, 2) if stop_atr is not None else None, to_hi=round(to_hi, 1), status=status,
                pre_breakout=status == "buy" and stop <= 5 and to_hi <= 5)


def scan_crypto():
    tickers = get_json(CDC + "get-tickers")["result"]["data"]
    best = {}
    for t in tickers:
        inst = t["i"]
        if "-" in inst or inst.count("_") != 1:
            continue
        base, quote = inst.split("_")
        if quote not in ("USD", "USDT") or base in STABLE:
            continue
        vv = float(t.get("vv") or 0)
        if vv > best.get(base, (0, ""))[0]:
            best[base] = (vv, inst)
    top = sorted(best.items(), key=lambda x: -x[1][0])[:50]
    now_ms = time.time() * 1000
    rows, failed = [], []
    for base, (_, inst) in top:
        try:
            data = get_json(f"{CDC}get-candlestick?instrument_name={inst}&timeframe=1D&count=300")["result"]["data"]
        except Exception:
            failed.append(base)
            continue
        data = sorted((x for x in data if x["t"] + 86_400_000 <= now_ms), key=lambda x: x["t"])
        row = evaluate(base, "crypto", [(float(x["h"]), float(x["l"]), float(x["c"])) for x in data])
        if row:
            row["asof"] = datetime.fromtimestamp(data[-1]["t"] / 1000, timezone.utc).strftime("%Y-%m-%d")
            rows.append(row)
        time.sleep(0.1)
    return rows, failed


def yahoo_bars(sym):
    res = get_json(YAHOO.format(sym))["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars, last = [], None
    for t, h, l, c in zip(res["timestamp"], q["high"], q["low"], q["close"]):
        if None in (h, l, c):
            continue
        bars.append((h, l, c))
        last = t
    meta = res.get("meta", {})
    # Drop today's bar while the US session is still open.
    period = meta.get("currentTradingPeriod", {}).get("regular", {})
    if bars and period and period.get("start", 0) <= time.time() < period.get("end", 0) and last >= period["start"]:
        bars.pop()
        last = None
    return bars, last


def scan_stocks():
    with urllib.request.urlopen(urllib.request.Request(SP500_CSV, headers=UA), timeout=30) as r:
        syms = [row["Symbol"].replace(".", "-") for row in csv.DictReader(io.StringIO(r.read().decode()))]

    def one(sym):
        try:
            bars, last = yahoo_bars(sym)
            row = evaluate(sym, "stock", bars)
            if row and last:
                row["asof"] = datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%d")
            return sym, row, None
        except Exception as e:
            return sym, None, str(e)

    rows, failed = [], []
    with ThreadPoolExecutor(6) as pool:
        for sym, row, err in pool.map(one, syms):
            if err:
                failed.append(sym)
            elif row:
                rows.append(row)
    return rows, failed, len(syms)


def fmt(x):
    if x >= 1000:
        return f"{x:,.0f}"
    if x >= 1:
        return f"{x:,.2f}"
    if x <= 0:
        return "0"
    digits = 3 - int(math.floor(math.log10(x)))  # 4 significant figures, no e-notation
    return f"{x:.{digits}f}"


def render(crypto, stocks, notes, stamp):
    rows = crypto + stocks
    buys = [r for r in rows if r["status"] == "buy"]
    pre_all = [r for r in buys if r["pre_breakout"]]
    ranked = sorted((r for r in pre_all if r["stop_atr"] is not None and r["stop_atr"] >= MIN_STOP_ATR),
                    key=lambda r: r["stop_atr"])
    pre = ranked[:TOP_N]
    e = html.escape
    method = ("Pre-breakout: in the buy zone, stop within 5% and price within 5% of its 20-day high, ranked by stop distance "
              "in ATR(14), stops inside 1 ATR left out. Buy zone: 20 EMA above a rising 50 EMA, daily low touched the 20 EMA "
              "in the last two bars, RSI(14) above 50. Exit: 20 EMA closes below 50 EMA, or price closes below 50 EMA. "
              f"Scanned {stamp} SGT.")
    # Only problems are shown; the routine coverage lines stay in latest.json.
    warnings = [n for n in notes if "failed" in n or "incomplete" in n]
    out = ['<!-- pullback:start -->', '<section class="pb reads">',
           '<style>.pb .pb-wrap{overflow-x:auto}.pb table{border-collapse:collapse;width:100%;font-size:13.5px;margin:6px 0 10px}'
           '.pb th,.pb td{border-bottom:1px solid var(--hair);padding:5px 6px;text-align:right;white-space:nowrap}'
           '.pb th{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}'
           '.pb th:first-child,.pb td:first-child,.pb th:nth-child(2),.pb td:nth-child(2){text-align:left}'
           '@media (max-width:600px){.pb th:nth-child(2),.pb td:nth-child(2){display:none}}'
           '.pb td:first-child{font-weight:700}.pb p{font-size:14.5px;margin:0 0 6px}'
           '.pb .under{color:var(--accent)}.pb .pb-note{font-size:12.5px;color:var(--accent);margin-top:8px}</style>',
           f'<h2 title="{e(method)}">Pullback Setups</h2>']
    if pre:
        out.append('<div class="pb-wrap"><table><tr><th>Name</th><th>Type</th><th>Close</th><th>vs 20 EMA</th>'
                   '<th>RSI</th><th>Stop (50 EMA)</th><th>Risk</th><th>Stop in ATR</th><th>To 20d high</th></tr>')
        # Under the 20 EMA: wait for a daily close back above it, so the cell is marked.
        for r in pre:
            out.append(f'<tr><td>{e(r["sym"])}</td><td>{r["kind"]}</td><td>{fmt(r["close"])}</td>'
                       f'<td{" class=under" if r["d20"] < 0 else ""}>{r["d20"]:+.1f}%</td><td>{r["rsi"]:.1f}</td><td>{fmt(r["e50"])}</td>'
                       f'<td>{r["stop_pct"]:.1f}%</td><td>{r["stop_atr"]:.1f}</td><td>{r["to_hi"]:.1f}%</td></tr>')
        out.append('</table></div>')
    else:
        out.append('<p>No pre-breakout setup today.</p>')
    if warnings:
        out.append(f'<p class="pb-note">{e(" ".join(warnings))}</p>')
    out += ['</section>', '<!-- pullback:end -->']
    return "\n".join(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    stamp = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    notes, crypto, stocks = [], [], []
    try:
        crypto, cfail = scan_crypto()
        notes.append(f"Crypto: top 50 by Crypto.com volume, closed UTC daily bars to {crypto[0]['asof'] if crypto else 'n/a'}"
                     + (f"; failed: {', '.join(cfail)}." if cfail else "."))
    except Exception as e:
        notes.append(f"Crypto scan failed ({type(e).__name__}).")
    try:
        stocks, sfail, total = scan_stocks()
        asof = max((r.get("asof", "") for r in stocks), default="n/a")
        notes.append(f"Stocks: {len(stocks)} of {total} S&P 500 names from Yahoo Finance, daily bars to {asof}"
                     + (f"; {len(sfail)} could not be fetched." if sfail else "."))
        if total and len(stocks) < total / 2:
            notes.append("Stock coverage is low today, so treat the stock list as incomplete.")
    except Exception as e:
        notes.append(f"Stock scan failed ({type(e).__name__}).")
    section = render(crypto, stocks, notes, stamp)
    with open(os.path.join(OUT, "section.html"), "w") as f:
        f.write(section)
    with open(os.path.join(OUT, "latest.json"), "w") as f:
        json.dump(dict(scanned_sgt=stamp, notes=notes, rows=crypto + stocks), f, indent=1)
    print(section)


if __name__ == "__main__":
    main()
