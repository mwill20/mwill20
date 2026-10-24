"""Tests for the card renderer and ledger. No network unless ONLINE=1.

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_cards as rc  # noqa: E402
import verify_ledger as vl  # noqa: E402

HOPS = json.loads((ROOT / "data" / "hops.json").read_text(encoding="utf-8"))


class RouteCard(unittest.TestCase):
    def test_seven_nodes_and_loop(self):
        svg = rc.render_route(HOPS["hops"], HOPS["loop_at"])
        self.assertEqual(svg.count("<circle"), 7)
        self.assertIn("loop · fill the gaps", svg)
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))

    def test_meters_never_decrease(self):
        meters = [h["meter"] for h in HOPS["hops"]]
        self.assertEqual(meters, sorted(meters))

    def test_ai_thread_absent_before_first_meter(self):
        # hop 1 has meter 0, so no violet segment may be drawn into it
        svg = rc.render_route(HOPS["hops"], HOPS["loop_at"])
        # six segments: into hops 2..7; none into hop 1 (meter 0)
        self.assertEqual(svg.count(f'stroke="{rc.VIOLET}"'), 6)
        zero = rc.render_route([dict(h, meter=0) for h in HOPS["hops"]], HOPS["loop_at"])
        self.assertEqual(zero.count(f'stroke="{rc.VIOLET}"'), 0)


class NowCard(unittest.TestCase):
    def test_renders_rows(self):
        svg = rc.render_now([{"name": "KC7-SecOps", "description": "Google SecOps drills", "pushed": "2026-10-17"}], "2026-10-24")
        self.assertIn("KC7-SecOps", svg)
        self.assertIn("2026-10-17", svg)

    def test_quiet_when_empty(self):
        svg = rc.render_now([], "2026-10-24")
        self.assertIn("no public pushes", svg)

    def test_escapes_markup_in_descriptions(self):
        svg = rc.render_now([{"name": "x", "description": '<script>alert(1)</script> & "q"', "pushed": ""}], "d")
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)


class PostureCard(unittest.TestCase):
    ROW_OK = {"name": "MalVec", "security": True, "tests": True, "ci": True, "pushed": "2026-04-28"}
    ROW_BAD = {"name": "LLM-Red-Teaming-Audit-Demo", "security": False, "tests": False, "ci": False, "pushed": "2025-11-27"}
    ROW_UNKNOWN = {"name": "ghost", "security": None, "tests": None, "ci": None, "pushed": ""}

    def test_missing_security_md_renders_red(self):
        """Should-fail case: a repo without SECURITY.md must show red, never green."""
        svg = rc.render_posture([self.ROW_BAD], "d")
        self.assertIn(rc.RED, svg)
        self.assertNotIn(rc.GREEN, svg)

    def test_full_posture_renders_green_only(self):
        svg = rc.render_posture([self.ROW_OK], "d")
        self.assertIn(rc.GREEN, svg)
        self.assertNotIn(rc.RED, svg)

    def test_unknown_is_grey_not_green(self):
        """An API failure must not be reported as a pass."""
        svg = rc.render_posture([self.ROW_UNKNOWN], "d")
        self.assertIn(rc.GREY, svg)
        self.assertNotIn(rc.GREEN, svg)


class Ledger(unittest.TestCase):
    def test_chain_verifies_and_detects_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.jsonl"
            rc.append_ledger(path, {"route.svg": "a" * 64}, "2026-10-24T00:00:00+00:00")
            rc.append_ledger(path, {"route.svg": "b" * 64}, "2026-10-25T00:00:00+00:00")
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(vl.verify(lines, None), [])
            # tamper with the first entry's card hash: both its hash and the chain must break
            tampered = [lines[0].replace("a" * 64, "c" * 64), lines[1]]
            problems = vl.verify(tampered, None)
            self.assertTrue(any("hash does not match" in p for p in problems))
            self.assertTrue(any("prev does not match" in p for p in problems))

    def test_card_mismatch_detected(self):
        with tempfile.TemporaryDirectory() as d:
            cards = Path(d) / "cards"
            cards.mkdir()
            (cards / "route.svg").write_text("<svg/>", encoding="utf-8")
            path = Path(d) / "ledger.jsonl"
            rc.append_ledger(path, {"route.svg": "0" * 64}, "t")
            problems = vl.verify(path.read_text(encoding="utf-8").splitlines(), cards)
            self.assertTrue(any("differs from ledger" in p for p in problems))


@unittest.skipUnless(os.environ.get("ONLINE") == "1", "set ONLINE=1 to check drift against the site")
class DriftAgainstSite(unittest.TestCase):
    def test_hops_match_content_md(self):
        req = urllib.request.Request(HOPS["source"], headers={"User-Agent": rc.UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            content = r.read().decode("utf-8")
        import re
        headings = re.findall(r"^## Hop (\d+)", content, re.M)
        self.assertEqual([int(h) for h in headings], [h["n"] for h in HOPS["hops"]])
        meters = [float(m) for m in re.findall(r"\*\*AI meter:\*\* ([\d.]+)", content)]
        self.assertEqual(meters, [float(h["meter"]) for h in HOPS["hops"][:-1]])
        loop = re.search(r"LOOP_AT = (\d+)", content)
        self.assertIsNotNone(loop)
        self.assertEqual(int(loop.group(1)), HOPS["loop_at"])


if __name__ == "__main__":
    unittest.main()
