"""Tests for prompt-cache health: re-write causes and the cold-cache (idle) compaction decision."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctx  # noqa: E402


def call(i, ts, cw, cr, model="claude-opus-5-5", ttl="1h"):
    """One assistant transcript line with usage."""
    cc = {f"ephemeral_{ttl}_input_tokens": cw}
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {"id": f"m{i}", "model": model,
                       "usage": {"input_tokens": 3, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr,
                                 "output_tokens": 100, "cache_creation": cc}}})


def boundary(ts, pre, post):
    """A compaction boundary line."""
    return json.dumps({"type": "system", "subtype": "compact_boundary", "timestamp": ts,
                       "compactMetadata": {"preTokens": pre, "postTokens": post}})


class CacheHealth(unittest.TestCase):
    def write(self, lines):
        """Transcript file from lines."""
        f = Path(tempfile.mkdtemp()) / "t.jsonl"
        f.write_text("\n".join(lines) + "\n")
        return f

    def test_causes(self):
        tp = self.write([
            call(1, "2026-11-21T10:00:00Z", 70000, 0),
            call(2, "2026-11-21T10:01:00Z", 2000, 70000),          # ordinary growth
            call(3, "2026-11-21T10:02:00Z", 60000, 12000),         # prefix changed while warm
            call(4, "2026-11-21T12:00:00Z", 74000, 0),             # 2 h later: idle
            call(5, "2026-11-21T12:01:00Z", 76000, 0, model="claude-sonnet-5-5"),  # model switch
        ])
        b = ctx.cache_report(tp)["busts"]
        self.assertEqual((b["prefix"]["n"], b["idle"]["n"], b["model"]["n"]), (1, 1, 1))

    def test_compaction_is_not_a_bust_and_idle_compaction_counts(self):
        tp = self.write([
            call(1, "2026-11-21T10:00:00Z", 70000, 0),
            call(2, "2026-11-21T10:01:00Z", 50000, 70000),
            boundary("2026-11-21T12:00:00Z", 120000, 80000),
            call(3, "2026-11-21T12:00:10Z", 80000, 0),
        ])
        r = ctx.cache_report(tp)
        self.assertEqual(sum(v["n"] for v in r["busts"].values()), 0)
        self.assertEqual(r["idle_compactions"], 1)
        self.assertEqual(r["_idle_pre"], 40000)

class Tune(unittest.TestCase):
    def test_opus_profile_lands_near_base_plus_100k(self):
        prof = {"g": [2000] * 40, "R": [33000] * 6, "P": [74000] * 6}
        w = ctx.tuned_window(prof, 72000, "claude-opus-5-5")
        self.assertTrue(200_000 <= w <= 240_000, w)

    def test_faster_growth_means_later_trigger(self):
        slow = ctx.tuned_window({"g": [1000] * 40}, 72000, "claude-opus-5-5")
        fast = ctx.tuned_window({"g": [6000] * 40}, 72000, "claude-opus-5-5")
        self.assertLess(slow, fast)

    def test_small_minus_p_run_never_goes_below_base(self):
        w = ctx.tuned_window({"g": [500] * 40, "R": [3000] * 6, "P": [9000] * 6}, 72000, "claude-opus-5-5")
        self.assertGreaterEqual(w * ctx.DEFAULT_PCT // 100, 72000 + ctx.TUNE_E[0])

    def test_200k_model_stays_native_when_cheaper(self):
        self.assertIsNone(ctx.tuned_window({"g": [5000] * 40}, 72000, "claude-haiku-5-5"))

    def test_apply_and_restore_remove_tuned_windows(self):
        s = {}
        ctx.apply_trigger(s, 220000, 80, {"claude-haiku-5-5": 190000, "claude-opus-5-5": 230000})
        self.assertEqual(s["modelSettings"]["claude-haiku-5-5"]["autoCompactWindow"], 190000)
        self.assertEqual(s["modelSettings"]["claude-opus-5-5"]["autoCompactWindow"], 230000)
        ctx.restore_trigger(s, {"models": {m: None for m in ctx.LONG_MODELS}, "tuned": ["claude-haiku-5-5"]})
        self.assertNotIn("modelSettings", s)


if __name__ == "__main__":
    unittest.main()
