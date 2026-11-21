"""Unit tests for ctx.py: digest content, task-list replay, Turkish decisions, savings. Run: python3 -m unittest discover system/tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ctx  # noqa: E402


# ---- transcript builders ----------------------------------------------------------------
def user(text, **kw):
    """A user prompt entry."""
    return {"type": "user", "message": {"role": "user", "content": text}, **kw}


def asst(*blocks, mid="m", usage=None):
    """An assistant entry with content blocks."""
    m = {"id": mid, "role": "assistant", "content": list(blocks)}
    if usage is not None:
        m["usage"] = {"input_tokens": usage, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return {"type": "assistant", "message": m}


def tool(tid, name, **inp):
    """A tool_use block."""
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def result(tid, text="", err=False):
    """A user entry carrying one tool_result."""
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": err}]}}


def text(t):
    """A text block."""
    return {"type": "text", "text": t}


class Digest(unittest.TestCase):
    """build_summary keeps what the agent needs to carry on."""

    def entries(self):
        return [
            user("fix the reel on the phone and post it"),
            asst(tool("p1", "mcp__ccd_turn__update_plan", items=[
                {"content": "Delete the post", "status": "in_progress"},
                {"content": "Find a trending sound", "status": "pending"},
                {"content": "Post it", "status": "pending"}]), mid="a1"),
            result("p1", "Plan shown"),
            asst(tool("p2", "mcp__ccd_turn__update_plan", advance=True), mid="a2"),
            result("p2", "ok"),
            asst(text("The audio was lost in the draft; rebuilding it from the file."), mid="a3"),
            *[e for i in range(3) for e in (asst(tool(f"b{i}", "Bash", command="adb shell input tap 1 2"), mid=f"t{i}"),
                                             result(f"b{i}", "(Bash completed with no output)"))],
            asst(tool("r1", "Read", file_path="/tmp/tel_s.png"), mid="r"),
            result("r1", ""),
        ]

    def test_digest_has_state_plan_findings_images(self):
        s = ctx.build_summary(Path("/p"), self.entries(), ".ctx/archive/L001-log.md")
        self.assertIn("MIDDLE of the latest request", s)
        self.assertIn("not a new message from the user", s)
        self.assertIn("- [x] Delete the post", s)
        self.assertIn("- [>] Find a trending sound", s)
        self.assertIn("- [ ] Post it", s)
        self.assertIn("The audio was lost in the draft", s)
        self.assertIn("/tmp/tel_s.png", s)
        # Three identical empty taps collapse into one line with a count, without a "result:" line.
        self.assertIn("adb shell input tap 1 2`  (×3)", s)
        self.assertNotIn("result: (Bash completed", s)

    def test_finished_turn_is_not_in_progress(self):
        e = [user("selam"), asst(text("Merhaba!"), mid="x")]
        self.assertFalse(ctx.turn_in_progress(e))
        self.assertNotIn("MIDDLE", ctx.build_summary(Path("/p"), e, "L"))

    def test_plan_done_after_wrap_up_is_hidden(self):
        e = self.entries() + [asst(tool("w", "mcp__ccd_turn__wrap_up", recap="bitti"), mid="w")]
        self.assertTrue(all(it["status"] == "completed" for it in ctx.plan_state(e)))
        self.assertNotIn("Your task list", ctx.build_summary(Path("/p"), e, "L"))

    def test_plan_done_and_start(self):
        plan = ctx.apply_plan_call([], "mcp__ccd_turn__update_plan", {"items": [
            {"content": "a", "status": "in_progress"}, {"content": "b", "status": "pending"}, {"content": "c", "status": "pending"}]})
        plan = ctx.apply_plan_call(plan, "mcp__ccd_turn__update_plan", {"done": [1], "start": 3})
        self.assertEqual([p["status"] for p in plan], ["completed", "pending", "in_progress"])
        plan = ctx.apply_plan_call(plan, "TodoWrite", {"todos": [{"content": "z", "status": "pending"}]})
        self.assertEqual(plan, [{"content": "z", "status": "pending"}])

    def test_recent_actions_not_listed_twice(self):
        s = ctx.build_summary(Path("/p"), self.entries(), "L")
        self.assertNotIn("Earlier tool actions", s)  # everything fits in the verbatim section


class TurkishDecisions(unittest.TestCase):
    """auto_capture copies Turkish decisions too."""

    def test_capture(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".ctx").mkdir()
            n = ctx.auto_capture(root, [
                "Bundan sonra tüm çıktılar Türkçe olsun. Bugün hava güzel.",
                "Portu 8080 yerine 9090 kullanalım.",
                "Ana rengin adı gece mavisi olsun lütfen."])
            got = (root / ".ctx" / "DECISIONS.md").read_text()
            self.assertEqual(n, 3, got)
            self.assertIn("Bundan sonra", got)
            self.assertIn("9090", got)
            self.assertNotIn("hava güzel", got)
            # Same decision again is not duplicated (Turkish letters count as words).
            self.assertEqual(ctx.auto_capture(root, ["Bundan sonra tüm çıktılar Türkçe olsun."]), 0)

    def test_words_keep_turkish_letters(self):
        self.assertIn("çıktılar", ctx.words("Çıktılar güzel"))

    def test_slug(self):
        self.assertEqual(ctx.slugify("Şarkı seçimi ÇÖZÜLDÜ"), "sarki-secimi-cozuldu")


class Savings(unittest.TestCase):
    """savings() compares with native compaction alone."""

    def write(self, rows):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for r in rows:
            f.write(json.dumps(r) + "\n")
        f.close()
        return Path(f.name)

    def boundary(self, pre, post):
        return {"type": "system", "subtype": "compact_boundary", "compactMetadata": {"preTokens": pre, "postTokens": post}}

    def test_no_compaction_no_saving(self):
        tp = self.write([asst(text("a"), mid=str(i), usage=10_000 + i) for i in range(5)])
        r = ctx.savings(tp)
        self.assertEqual((r["saved"], r["requests"], r["compactions"]), (0, 5, 0))

    def test_early_compaction_saves_dropped_tokens_per_request(self):
        rows = [asst(text("a"), mid="1", usage=60_000), self.boundary(60_000, 10_000),
                user("[last-token compaction: x]"), asst(text("b"), mid="2", usage=12_000),
                asst(text("c"), mid="3", usage=14_000)]
        r = ctx.savings(self.write(rows))
        self.assertEqual(r["saved"], 2 * 50_000)
        self.assertEqual((r["compactions"], r["deterministic"]), (1, 1))
        self.assertEqual(r["context"], 14_000)

    def test_native_compaction_is_not_ours(self):
        rows = [asst(text("a"), mid="1", usage=165_000), self.boundary(165_000, 15_000), asst(text("b"), mid="2", usage=20_000)]
        self.assertEqual(ctx.savings(self.write(rows))["saved"], 0)

    def test_counterfactual_caps_at_native_limit(self):
        # 3 early compactions of 60K each; without them context would pass 167K and natively compact.
        rows = []
        for i in range(3):
            rows += [asst(text("x"), mid=f"a{i}", usage=70_000), self.boundary(70_000, 10_000)]
        rows += [asst(text("y"), mid="z", usage=20_000)]
        r = ctx.savings(self.write(rows))
        # a1: +60K. a2: 70K+120K = 190K > 167K → native would compact (a 190K summarizer call), keeps 20K → +20K.
        # z: 20K+60K → +80K. Our 3 compactions used the summarizer (no digest row): −3×70K.
        self.assertEqual(r["saved"], 60_000 + 20_000 + 80_000 + 190_000 - 210_000)


class GlobalMode(unittest.TestCase):
    """global on/off, per-folder store, user-level hooks that step aside in projects."""

    def setUp(self):
        import io
        self.io = io
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name).resolve()  # macOS: /var -> /private/var
        self.saved = (ctx.LT_HOME, ctx.GLOBAL_FLAG, ctx.STORE, ctx.USER_SETTINGS, ctx.MOD_HOME)
        self.saved_tune, ctx.TUNE_PROJECTS = ctx.TUNE_PROJECTS, Path(tempfile.mkdtemp())
        self.temp_dirs, ctx.TEMP_DIRS = ctx.TEMP_DIRS, ()  # test folders live under /tmp
        ctx.LT_HOME, ctx.GLOBAL_FLAG, ctx.STORE = t / "lt", t / "lt" / "global.json", t / "lt" / "store"
        ctx.USER_SETTINGS, ctx.MOD_HOME = t / "settings.json", t / "lt" / "mod"
        ctx.USER_SETTINGS.write_text(json.dumps({"env": {"KEEP": "1"}, "autoCompactWindow": 300000,
                                                 "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "mine.sh"}]}]}}))
        self.plain = t / "home" / "work"
        self.plain.mkdir(parents=True)
        self.proj = t / "proj"
        (self.proj / ".ctx").mkdir(parents=True)
        (self.proj / ".ctx" / "ctx.py").write_text("")

    def tearDown(self):
        ctx.LT_HOME, ctx.GLOBAL_FLAG, ctx.STORE, ctx.USER_SETTINGS, ctx.MOD_HOME = self.saved
        ctx.TUNE_PROJECTS = self.saved_tune
        ctx.TEMP_DIRS = self.temp_dirs
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.tmp.cleanup()

    def run_hook(self, fn, data, *args):
        """Call a hook with JSON on stdin, return its stdout."""
        old_in, old_out = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = self.io.StringIO(json.dumps(data)), self.io.StringIO()
        try:
            fn(list(args))
            return sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = old_in, old_out

    def quiet(self, fn, args):
        """Run a command with stdout swallowed."""
        old = sys.stdout
        sys.stdout = self.io.StringIO()
        try:
            return fn(args)
        finally:
            sys.stdout = old

    def test_on_off_restores_user_settings(self):
        self.quiet(ctx.cmd_global, ["on"])
        self.quiet(ctx.cmd_global, ["on"])  # idempotent
        s = json.loads(ctx.USER_SETTINGS.read_text())
        self.assertEqual(s["autoCompactWindow"], 300000)  # the user's own top-level value is kept
        w = s["modelSettings"]["claude-opus-5-5"]["autoCompactWindow"]; self.assertTrue(ctx.MIN_WORK < w * 0.8 < 400000)
        self.assertEqual(s["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"], "80")
        self.assertEqual([len(s["hooks"][e]) for e in ("SessionStart", "PreCompact", "PreToolUse")], [2, 1, 1])
        self.assertTrue(ctx.global_enabled())
        self.quiet(ctx.cmd_global, ["off"])
        s = json.loads(ctx.USER_SETTINGS.read_text())
        self.assertEqual(s, {"env": {"KEEP": "1"}, "autoCompactWindow": 300000,
                             "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "mine.sh"}]}]}})
        self.assertFalse(ctx.global_enabled())

    def test_store_and_session_hook(self):
        self.assertEqual(ctx.resolve_root(self.plain), self.plain.resolve())  # off: no store
        self.quiet(ctx.cmd_global, ["on"])
        root = ctx.resolve_root(self.plain)
        self.assertTrue(ctx.is_store(root))
        self.assertEqual(ctx.resolve_root(self.proj / "sub"), self.proj)  # projects keep their own .ctx
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.plain)
        self.quiet(ctx.cmd_decide, ["language: English"])
        out = self.run_hook(ctx.hook_session, {"cwd": str(self.plain)}, "--global")
        self.assertIn("active in this session (global mode)", out)
        self.assertIn("- language: English", out)
        self.assertIn("--at", out)
        self.assertEqual(self.run_hook(ctx.hook_session, {"cwd": str(self.proj)}, "--global"), "")

    def test_global_guard_steps_aside_in_projects(self):
        self.quiet(ctx.cmd_global, ["on"])
        big = self.proj / "big.txt"
        big.write_text("x\n" * 5000)
        data = {"tool_name": "Read", "tool_input": {"file_path": str(big)}, "cwd": str(self.proj)}
        self.assertEqual(self.run_hook(ctx.hook_guard, data, "--global"), "")   # project hook handles it
        self.assertIn("deny", self.run_hook(ctx.hook_guard, data))              # the project's own hook
        data["cwd"] = str(self.plain)
        self.assertIn("deny", self.run_hook(ctx.hook_guard, data, "--global"))  # outside projects: global guards

    def test_health(self):
        self.quiet(ctx.cmd_global, ["on"])
        h = ctx.health(self.plain, None)
        self.assertEqual(h["mode"], "global")
        self.assertTrue(all(c["ok"] for c in h["checks"]), h["checks"])
        self.assertEqual(ctx.health(self.proj, None)["mode"], "project")


if __name__ == "__main__":
    unittest.main()
