"""Run: python -m unittest discover -s scan/tests  (the rendering tests need node)"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import build_app  # noqa: E402

BREAKOUTS = {"made_ms": 1, "bar_day": 20000, "breakouts": []}
WATCH = {"names": {"TER": {"level": 100.0}}}


def feed(**override):
    """jev() on a feed directory; override maps a file stem (with _) to raw text, or None to leave it out."""
    files = {f"{s}-{k}": json.dumps(v) for s in ("prebreak", "growth")
             for k, v in (("breakouts", BREAKOUTS), ("watch", WATCH))}
    files.update({k.replace("_", "-"): v for k, v in override.items()})
    with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
        os.mkdir(os.path.join(d, "state"))
        for name, raw in files.items():
            if raw is not None:
                with open(os.path.join(d, "state", name + ".json"), "w", encoding="utf-8") as f:
                    f.write(raw)
        return build_app.jev(d)


def render(**data):
    base = dict(built="2026-11-25 08:00", work_url=None, errors={}, edition=None, pullback=None, setups=None,
                breakouts=None, jev=None)
    out = subprocess.run(["node", os.path.join(HERE, "render_app.js")], input=json.dumps({**base, **data}),
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


class JevFeed(unittest.TestCase):
    def test_readable_feed_with_no_breakouts_is_empty(self):
        self.assertEqual(feed()["prebreak"]["breakouts"], [])
        self.assertEqual([w["ticker"] for w in feed()["prebreak"]["watch"]], ["TER"])

    def test_corrupt_breakouts_are_unavailable_and_other_sleeve_survives(self):
        j = feed(prebreak_breakouts="{bad")
        self.assertIsNone(j["prebreak"]["breakouts"])
        self.assertEqual(j["growth"]["breakouts"], [])

    def test_missing_or_wrong_shape_is_unavailable(self):
        for raw in (None, "[]", "{}", '{"breakouts": [{}]}'):
            with self.subTest(raw=raw):
                self.assertIsNone(feed(growth_breakouts=raw)["growth"]["breakouts"])

    def test_corrupt_watch_list_is_unavailable(self):
        self.assertIsNone(feed(growth_watch="{bad")["growth"]["watch"])


@unittest.skipUnless(shutil.which("node"), "needs node")
class Rendering(unittest.TestCase):
    def test_empty_feed_says_no_breakouts(self):
        self.assertEqual(render(jev=feed())["stocks"].count("No breakouts."), 2)

    def test_corrupt_breakouts_show_unavailable(self):
        page = render(jev=feed(prebreak_breakouts="{bad"))
        self.assertEqual(page["stocks"].count("No breakouts."), 1)
        self.assertIn("Breakouts unavailable.", page["stocks"])
        self.assertIn("jev-trader breakouts unavailable.", page["today"])

    def test_corrupt_watch_list_shows_unavailable(self):
        self.assertIn("Watch list unavailable.", render(jev=feed(growth_watch="{bad"))["stocks"])

    def test_feed_that_failed_to_build_is_not_called_unconnected(self):
        page = render(errors={"jev": "KeyError"})
        self.assertNotIn("Not connected", page["stocks"])
        self.assertIn("jev is unavailable", page["stocks"])
        self.assertIn("jev-trader breakouts unavailable.", page["today"])

    def test_crypto_table_shows_rsi_to_one_decimal(self):
        row = dict(coin="ETH", bias="neutral", entry=None, stop=None, target=None, rr=None, rsi=44.6,
                   structure="HH+HL", strict=False, missing="x")
        self.assertIn("<td>44.6</td>", render(setups=dict(rows=[row], failed=[]))["crypto"])

    def test_today_lists_last_close_breakouts_by_distance_over_level(self):
        j = feed()
        j["growth"]["bar_day"] = "2026-11-24"
        j["growth"]["breakouts"] = [dict(ticker="AAA", close=101.0, level=100.0, vol_ratio=1, rev_yoy=None, day="2026-11-24"),
                                    dict(ticker="BBB", close=105.0, level=100.0, vol_ratio=1, rev_yoy=None, day="2026-11-24"),
                                    dict(ticker="OLD", close=150.0, level=100.0, vol_ratio=1, rev_yoy=None, day="2026-10-01")]
        today = render(jev=j)["today"]
        self.assertIn("2 breakouts, 24 Nov close", today)
        self.assertLess(today.index("BBB"), today.index("AAA"))
        self.assertNotIn("OLD", today)

    def test_unconnected_jev_is_not_called_unavailable(self):
        self.assertIn("jev-trader is not connected.", render()["today"])

    def test_paper_shows_story_note_and_escapes_text(self):
        ed = dict(date="2026-11-25", file="2026-11-25.html", lead=dict(url="https://x.test/a", title="Lead <b>"),
                  dek="Dek", byline="Src \u00b7 Tue 24 Nov 2026 \u00b7 Read the original \u2197", why="Why",
                  story=["First para", "Second para"], note="Reddit was down.", editions=["2026-11-25", "2026-11-23"],
                  briefs=[dict(url="javascript:alert(1)", title="B1", src="S", body="Body", why="W")], reads=[])
        paper = render(edition=ed)["paper"]
        self.assertIn("Lead &lt;b&gt;", paper)
        self.assertIn("Full story", paper)
        self.assertIn("Reddit was down.", paper)
        self.assertNotIn("javascript:", paper)
        self.assertNotIn("Read the original", paper)
        self.assertIn('2026-11-23.html', paper)

    def test_no_setup_and_no_fresh_cross_summary(self):
        row = dict(coin="BTC", bias="neutral", entry=None, stop=None, target=None, rr=None, rsi=24.6,
                   structure="HH+HL", strict=False, missing="4H HH+HL against daily trend")
        today = render(setups=dict(rows=[row], failed=[]), breakouts=dict(rows=[], skipped=[]))["today"]
        self.assertIn("No setup in 1 coin. No fresh EMA cross.", today)

    def test_feed_numbers_that_are_not_numbers_never_become_markup(self):
        bad = '"><img src=x>'
        row = dict(sym="JNJ", kind="stock", close=1.0, d20=bad, rsi=bad, e50=bad, stop_pct=bad, stop_atr=bad, to_hi=bad,
                   pre_breakout=True)
        pb = dict(scanned="x", notes=[], total=1, noise=0, buy_zone=1, rows=[row], all=[row])
        bo = dict(rows=[dict(coin="BTC", label="FRESH-CROSS", gap=bad, cross_days=bad, vs_sma200=bad, d7=bad,
                             range14=bad, vol_k=bad, thin=False)], skipped=[])
        page = render(pullback=pb, breakouts=bo)
        for tab in ("today", "stocks", "crypto"):
            self.assertNotIn("<img", page[tab])

    def test_edition_without_new_fields_still_renders(self):
        ed = dict(date="2026-11-20", file="2026-11-20.html", lead=dict(url="https://x.test/a", title="Lead"), dek="D",
                  byline="B", why="", briefs=[dict(url="https://x.test/b", title="B1", body="Body", why="W")], reads=[])
        paper = render(edition=ed)["paper"]
        self.assertIn("Lead", paper)
        self.assertIn("20 Nov", paper)


def desktop(state, exec_result, data=None):
    data = data or dict(built="2026-11-25 08:00", work_url=None, errors={}, edition=None, pullback=None, setups=None,
                        breakouts=None, jev=None)
    out = subprocess.run(["node", os.path.join(HERE, "desktop_app.js")],
                         input=json.dumps(dict(data=data, state=state, exec=exec_result)),
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


@unittest.skipUnless(shutil.which("node"), "needs node")
class DesktopApp(unittest.TestCase):
    def test_not_granted_asks_from_a_button_and_runs_nothing(self):
        r = desktop("prompt", None)
        self.assertIn("Turn on live updates", r["live"])
        self.assertEqual(r["execs"], 0)

    def test_denied_offers_to_change_the_permission(self):
        r = desktop("denied", None)
        self.assertIn("Change permission", r["live"])
        self.assertEqual(r["execs"], 0)

    def test_curl_failure_is_reported_in_plain_words(self):
        r = desktop("granted", dict(stdout="", stderr="", code=22, signal=None, truncated=False))
        self.assertIn("no connection, or the feed is not published yet", r["live"])

    def test_newer_feed_is_shown(self):
        new = dict(built="2026-11-26 07:35", work_url=None, errors={}, edition=None, setups=None, breakouts=None,
                   jev=None, pullback=dict(scanned="x", notes=[], total=7, noise=0, buy_zone=7, rows=[], all=[]))
        r = desktop("granted", dict(stdout=json.dumps(new), stderr="", code=0, signal=None, truncated=False))
        self.assertIn("Live feed, built 2026-11-26 07:35", r["live"])
        self.assertIn("7 pre-breakouts", r["today"])

    def test_unreadable_feed_keeps_the_old_page(self):
        r = desktop("granted", dict(stdout="<html>", stderr="", code=0, signal=None, truncated=False))
        self.assertIn("the feed was not readable", r["live"])
        self.assertIn("2026-11-25 08:00", r["live"])


class EditionParse(unittest.TestCase):
    def test_old_why_box_with_bold_label(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "2026-10-01.html"), "w", encoding="utf-8") as f:
                f.write('<h1><a href="https://x.test/a">Lead</a></h1><div class="story"><p>One</p>'
                        '<div class="why-box"><b>Why it matters to you.</b> Because <b>this</b>.</div></div>')
            ed = build_app.edition(d)
        self.assertEqual(ed["why"], "Because this.")
        self.assertEqual(ed["story"], ["One"])

    def test_reads_story_why_note_and_editions(self):
        site = os.path.dirname(os.path.dirname(HERE))
        with tempfile.TemporaryDirectory() as d:
            for f in ("2026-11-23.html", "2026-11-25.html"):
                shutil.copy(os.path.join(site, f), d)
            ed = build_app.edition(d)
        self.assertEqual(ed["date"], "2026-11-25")
        self.assertEqual(ed["editions"], ["2026-11-25", "2026-11-23"])
        self.assertEqual(len(ed["story"]), 4)
        self.assertTrue(ed["why"].startswith("If you run unattended"))
        self.assertTrue(ed["note"].startswith("Reddit and X"))
        self.assertEqual(ed["briefs"][0]["src"], "Claude blog (Anthropic) \u00b7 Tue 24 Nov 2026")


if __name__ == "__main__":
    unittest.main()
