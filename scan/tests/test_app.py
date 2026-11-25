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
        self.assertIn("<b>–</b><span>jev breakouts today</span><small>unavailable</small>", page["today"])
        self.assertIn('<span>jev-trader</span><span class="bad">', page["today"])

    def test_corrupt_watch_list_shows_unavailable(self):
        self.assertIn("Watch list unavailable.", render(jev=feed(growth_watch="{bad"))["stocks"])

    def test_feed_that_failed_to_build_is_not_called_unconnected(self):
        page = render(errors={"jev": "KeyError"})
        self.assertNotIn("Not connected", page["stocks"])
        self.assertIn("jev is unavailable", page["stocks"])
        self.assertIn("<span>jev breakouts today</span><small>unavailable</small>", page["today"])

    def test_crypto_table_shows_rsi_to_one_decimal(self):
        row = dict(coin="ETH", bias="neutral", entry=None, stop=None, target=None, rr=None, rsi=44.6,
                   structure="HH+HL", strict=False, missing="x")
        self.assertIn("<td>44.6</td>", render(setups=dict(rows=[row], failed=[]))["crypto"])


if __name__ == "__main__":
    unittest.main()
