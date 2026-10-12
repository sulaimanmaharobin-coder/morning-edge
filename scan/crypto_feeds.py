"""Crypto feeds for the Morning Edge app, from the Crypto.com public API.

watchlist_setups(): the 8am/8pm watchlist rules on six coins.
  Bullish: 1D close above 1D EMA50, daily RSI 45-70, HH+HL on 4H.
  Bearish: 1D close below 1D EMA50, daily RSI <= 45, LH+LL on 4H.
  Long: entry = last 4H close, stop = latest 4H swing low - 0.5 x 4H ATR14,
  target = nearest 1D swing high above entry (shorts mirror). Strict = RR >= 2.
breakout_scan(): the daily EMA 20/50 breakout labels on liquid USD pairs
  (FRESH-CROSS, NEAR-CROSS, IN-TREND, CHASING, QUIET-SETUP).
Closed candles only. Standard library only.
"""
import json
import time
import urllib.request

from pullback_scan import ema, rsi

CDC = "https://api.crypto.com/exchange/v1/public/"
WATCHLIST = ["BTC", "ETH", "SOL", "LINK", "AVAX", "SUI"]
STABLE = {"USDT", "USDC", "DAI", "PYUSD", "FDUSD", "TUSD", "USD1", "RLUSD", "EURC", "USDE", "PAXG", "XAUT", "USAT"}
TF_MS = {"4h": 4 * 3_600_000, "1D": 86_400_000, "7D": 7 * 86_400_000}


def get(method, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = CDC + method + ("?" + q if q else "")
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                d = json.load(r)["result"]["data"]
            if not d:
                raise ValueError("empty data")
            return d
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"{method} {params}: {e}")
            time.sleep(2)


def candles(inst, tf, count=300):
    now = time.time() * 1000
    data = get("get-candlestick", instrument_name=inst, timeframe=tf, count=count)
    data = sorted((x for x in data if x["t"] + TF_MS[tf] <= now), key=lambda x: x["t"])
    return dict(h=[float(x["h"]) for x in data], l=[float(x["l"]) for x in data],
                c=[float(x["c"]) for x in data], v=[float(x["v"]) for x in data], t=[x["t"] for x in data])


def wilder_atr(h, l, c, n=14):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    a = sum(tr[:n]) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a


def swings(h, l):
    """2-bar fractal swing highs and lows as (index, price), oldest first."""
    sh = [(i, h[i]) for i in range(2, len(h) - 2) if h[i] > max(h[i - 2], h[i - 1], h[i + 1], h[i + 2])]
    sl = [(i, l[i]) for i in range(2, len(l) - 2) if l[i] < min(l[i - 2], l[i - 1], l[i + 1], l[i + 2])]
    return sh, sl


def macd_hist(c):
    f, s = ema(c, 12), ema(c, 26)
    line = [a - b for a, b in zip(f, s) if a is not None and b is not None]
    sig = ema(line, 9)
    return [m - g for m, g in zip(line, sig) if g is not None]


def watchlist_setups():
    rows, failed = [], []
    for coin in WATCHLIST:
        try:
            inst = f"{coin}_USDT"
            try:
                d1 = candles(inst, "1D")
            except RuntimeError:
                inst = f"{coin}_USD"
                d1 = candles(inst, "1D")
            h4, w1 = candles(inst, "4h"), candles(inst, "7D", 210)
        except RuntimeError:
            failed.append(coin)
            continue
        c = d1["c"]
        e50, r = ema(c, 50)[-1], rsi(c)[-1]
        wk = ema(w1["c"], 50)[-1] if len(w1["c"]) >= 50 else None
        sh4, sl4 = swings(h4["h"], h4["l"])
        if len(sh4) >= 2 and len(sl4) >= 2 and sh4[-1][1] > sh4[-2][1] and sl4[-1][1] > sl4[-2][1]:
            struct = "HH+HL"
        elif len(sh4) >= 2 and len(sl4) >= 2 and sh4[-1][1] < sh4[-2][1] and sl4[-1][1] < sl4[-2][1]:
            struct = "LH+LL"
        else:
            struct = "no clear structure"
        if c[-1] > e50 and 45 <= r <= 70 and struct == "HH+HL":
            bias = "bullish"
        elif c[-1] < e50 and r <= 45 and struct == "LH+LL":
            bias = "bearish"
        else:
            bias = "neutral"
        hist = macd_hist(c)
        vol20 = sum(h4["v"][-21:-1]) / 20
        row = dict(coin=coin, close=c[-1], ema50=e50, rsi=round(r, 1), structure=struct, bias=bias,
                   weekly_aligned=None if wk is None else (w1["c"][-1] > wk) == (bias == "bullish"),
                   macd_rising=len(hist) > 1 and hist[-1] > hist[-2],
                   vol_ratio=round(h4["v"][-1] / vol20, 2) if vol20 else None,
                   entry=None, stop=None, target=None, rr=None, strict=False, missing=None)
        if bias != "neutral":
            a4 = wilder_atr(h4["h"], h4["l"], h4["c"])
            entry = h4["c"][-1]
            shd, sld = swings(d1["h"], d1["l"])
            if bias == "bullish":
                stop = sl4[-1][1] - 0.5 * a4
                above = [p for _, p in shd if p > entry]
                target = min(above) if above else None
            else:
                stop = sh4[-1][1] + 0.5 * a4
                below = [p for _, p in sld if p < entry]
                target = max(below) if below else None
            risk = abs(entry - stop)
            rr = abs(target - entry) / risk if target is not None and risk else None
            row.update(entry=entry, stop=stop, target=target, rr=round(rr, 2) if rr else None,
                       strict=rr is not None and rr >= 2)
            if not row["strict"]:
                row["missing"] = "no defined target" if target is None else f"RR {rr:.1f} below 2"
        else:
            miss = []
            if c[-1] > e50 and r < 45:
                miss.append(f"RSI {r:.0f} below 45 above EMA50")
            elif c[-1] > e50 and r > 70:
                miss.append(f"RSI {r:.0f} above 70")
            elif c[-1] < e50 and r > 45:
                miss.append(f"below EMA50 but RSI {r:.0f} above 45")
            if struct == "no clear structure":
                miss.append("no clear 4H structure")
            elif (struct == "HH+HL") != (c[-1] > e50):
                miss.append(f"4H {struct} against daily trend")
            row["missing"] = "; ".join(miss) or "mixed signals"
        rows.append(row)
        time.sleep(0.1)
    rows.sort(key=lambda x: (not x["strict"], not x["weekly_aligned"], not x["macd_rising"],
                             -(x["vol_ratio"] or 0), -(x["rr"] or 0)))
    return rows, failed


def breakout_scan():
    rows, skipped = [], []
    now_ms = time.time() * 1000
    for t in get("get-tickers"):
        i = t["i"]
        if not i.endswith("_USD") or "-" in i:
            continue
        coin = i[:-4]
        if coin in STABLE:
            continue
        vol, b, k = float(t.get("vv") or 0), float(t.get("b") or 0), float(t.get("k") or 0)
        if vol < 25_000 or b <= 0 or k <= 0:
            continue
        spread = (k - b) / ((k + b) / 2) * 1e4
        if spread > 50:
            continue
        liquid = vol >= 100_000 and spread <= 25
        try:
            bars = get("get-candlestick", instrument_name=i, timeframe="1D", count=300)
        except RuntimeError:
            skipped.append(coin)
            continue
        bars = sorted((x for x in bars if x["t"] + 86_400_000 <= now_ms), key=lambda x: x["t"])
        c = [float(x["c"]) for x in bars]
        vu = [float(x["v"]) * float(x["c"]) for x in bars]
        time.sleep(0.1)
        if len(c) < 201:
            continue
        f, s = _ema_seeded(c, 20), _ema_seeded(c, 50)
        gap, gap5 = f[-1] / s[-1] - 1, f[-6] / s[-6] - 1
        since = next((len(c) - 1 - j for j in range(len(c) - 1, 0, -1) if (f[j] > s[j]) != (f[j - 1] > s[j - 1])), None)
        sma200 = sum(c[-201:-1]) / 200
        d1, d7 = c[-1] / c[-2] - 1, c[-1] / c[-8] - 1
        rng14 = max(c[-14:]) / min(c[-14:]) - 1
        gate = c[-1] > sma200 and d1 < 0.15 and d7 < 0.30 and rng14 < 0.50
        if gap > 0:
            label = ("FRESH-CROSS" if since is not None and since < 3 else "IN-TREND") if gate else (
                "CHASING" if c[-1] > sma200 else None)
        else:
            label = "NEAR-CROSS" if gap > -0.02 and gap > gap5 else None
        if not liquid:
            label = None
        if not label and -0.015 <= gap <= 0.02 and -0.12 <= c[-1] / sma200 - 1 <= 0.03 and rng14 < 0.15 and abs(d7) < 0.10:
            label = "QUIET-SETUP"
        if label:
            v30 = sum(vu[-37:-7]) / 30
            rows.append(dict(coin=coin, label=label, gap=round(gap * 100, 1), cross_days=since,
                             vs_sma200=round((c[-1] / sma200 - 1) * 100), d1=round(d1 * 100, 1),
                             d7=round(d7 * 100), range14=round(rng14 * 100), spread=round(spread, 1),
                             vol_k=round(vol / 1e3), thin=not liquid,
                             vol_ratio=round(sum(vu[-7:]) / 7 / v30, 2) if v30 else None))
    order = ["FRESH-CROSS", "NEAR-CROSS", "IN-TREND", "CHASING", "QUIET-SETUP"]
    rows.sort(key=lambda r: (order.index(r["label"]), -r["vol_k"]))
    return rows, skipped


def _ema_seeded(xs, n):
    # Same EMA as the existing breakout-scan routine (seeded on the first close).
    a, e, out = 2 / (n + 1), xs[0], []
    for x in xs:
        e = a * x + (1 - a) * e
        out.append(e)
    return out
