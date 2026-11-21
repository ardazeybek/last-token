"""Regression tests for the 2026-11-20 audit: each test is one finding. Run: python3 -m unittest discover system/tests"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ctx  # noqa: E402
from test_ctx import asst, result, text, tool, user  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def uid(entries):
    """Give every entry a uuid, as real transcripts have."""
    for i, e in enumerate(entries):
        e.setdefault("uuid", f"u{i}")
    return entries


def run_io(fn, args, stdin=""):
    """Call a command with stdin, return (exit code, stdout)."""
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = io.StringIO(stdin), io.StringIO()
    try:
        code = fn(args)
        return code, sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = old_in, old_out


class Sandbox(unittest.TestCase):
    """Every path ctx.py writes points into a temp folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.saved = (ctx.LT_HOME, ctx.GLOBAL_FLAG, ctx.STORE, ctx.USER_SETTINGS, ctx.MOD_HOME, ctx.PAUSED)
        ctx.LT_HOME = self.t / "lt"
        ctx.GLOBAL_FLAG, ctx.STORE = ctx.LT_HOME / "global.json", ctx.LT_HOME / "store"
        ctx.USER_SETTINGS, ctx.MOD_HOME, ctx.PAUSED = self.t / "settings.json", ctx.LT_HOME / "mod", ctx.LT_HOME / "paused.json"
        self.proj = self.t / "proj"
        (self.proj / ".ctx").mkdir(parents=True)
        (self.proj / ".ctx" / "ctx.py").write_text("")
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.proj)
        self.saved_tune, ctx.TUNE_PROJECTS = ctx.TUNE_PROJECTS, self.t / "projects"

    def tearDown(self):
        ctx.TUNE_PROJECTS = self.saved_tune
        (ctx.LT_HOME, ctx.GLOBAL_FLAG, ctx.STORE, ctx.USER_SETTINGS, ctx.MOD_HOME, ctx.PAUSED) = self.saved
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        self.tmp.cleanup()


class DigestKeepsTheRequest(unittest.TestCase):
    """A3: the deterministic digest must not lose what the person asked."""

    def summary(self, entries, all_entries=None):
        entries = uid(entries)
        return ctx.build_summary(Path("/x"), entries, "x", all_entries or entries)

    def test_repeated_short_prompt_is_kept(self):
        e = [user("evet"), asst(text("emin misin?"), mid="a"), user("evet")]
        self.assertEqual(ctx.segment_facts(uid(e))[0], ["evet", "evet"])

    def test_corrected_long_prompt_wins(self):
        base = "Please do this " + "a" * 400
        e = [user(base + " PORT 8080"), asst(text("ok"), mid="a"), user(base + " NO PORT 9090")]
        self.assertIn("9090", ctx.segment_facts(uid(e))[0][-1])

    def test_pasted_html_and_slash_command_count_as_requests(self):
        e = [user('<pasted_content id="1">log line</pasted_content> fix this'), asst(text("ok"), mid="a"),
             user("<command-message>zirve</command-message>\n<command-name>/zirve</command-name>\n<command-args>site yap</command-args>")]
        prompts = ctx.segment_facts(uid(e))[0]
        self.assertTrue(prompts[0].startswith("<pasted_content"))
        self.assertEqual(prompts[1], "/zirve site yap")

    def test_notifications_and_command_output_are_not_requests(self):
        e = [user("the real task"), user("<task-notification>done</task-notification>"),
             user("<local-command-stdout>x</local-command-stdout>")]
        self.assertEqual(ctx.segment_facts(uid(e))[0], ["the real task"])

    def test_long_prompt_keeps_its_end_and_says_it_was_cut(self):
        out = self.summary([user("a" * 6000 + " SON KURAL: testleri silme")])
        self.assertIn("SON KURAL", out)
        self.assertIn("chars cut here", out)

    def test_agent_report_keeps_its_start(self):
        rep = "BULGU-1 kritik\n" + "detay\n" * 400 + "SON"
        e = [user("search"), asst(tool("g", "Agent", prompt="find bugs"), mid="a"), result("g", rep), asst(text("ok"), mid="b")]
        out = self.summary(e)
        self.assertIn("BULGU-1", out)
        self.assertIn("SON", out)

    def test_running_call_is_listed(self):
        e = [user("do the job"), asst(tool("b1", "Bash", command="echo one"), mid="a"), result("b1", "one-out"),
             asst(tool("b2", "Bash", command="make deploy-prod"), mid="b")]
        out = self.summary(e)
        self.assertIn("make deploy-prod", out)
        self.assertIn("none yet", out)

    def test_slash_command_output_is_not_mid_turn(self):
        e = uid([user("selam"), asst(text("selam!"), mid="a"), user("<local-command-stdout>ok</local-command-stdout>")])
        self.assertFalse(ctx.turn_in_progress(e))

    def test_request_of_an_earlier_segment_survives(self):
        old = [user("Add 3 repo suggestions to the daily report and schedule the Instagram post"), asst(text("starting"), mid="a"),
               {"type": "system", "subtype": "compact_boundary"}]
        seg = [user("my internet dropped, continue"), asst(text("continuing"), mid="b")]
        all_e = uid(old + seg)
        out = ctx.build_summary(Path("/x"), all_e[3:], "x", all_e)
        self.assertIn("3 repo suggestions", out)
        self.assertIn("my internet dropped", out)

    def test_extra_block_has_requests_and_plan(self):
        e = uid([user("My long, real request: redesign the site from scratch, make it mobile friendly"),
                 asst(tool("p", "mcp__ccd_turn__update_plan", items=[{"content": "Design", "status": "in_progress"}]), mid="a"),
                 user("continuing")])
        out = ctx.build_extra(Path("/x"), e, "L001")
        self.assertTrue(out.startswith(ctx.DIGEST_HEAD))
        self.assertIn("redesign the site", out)
        self.assertIn("- continuing", out)
        self.assertIn("[>] Design", out)


class Memory(Sandbox):
    """B6-B9: decisions and recall."""

    def test_changed_decision_replaces_the_old_one(self):
        d = ctx.ctx_dir(self.proj) / "DECISIONS.md"
        d.write_text("- (user) Bundan sonra port 8080 kullan.\n")
        ctx.auto_capture(self.proj, ["Bundan sonra port 9090 kullan."])
        self.assertIn("9090", d.read_text())
        self.assertNotIn("8080", d.read_text())

    def test_same_decision_is_not_duplicated(self):
        d = ctx.ctx_dir(self.proj) / "DECISIONS.md"
        ctx.auto_capture(self.proj, ["Bundan sonra port 9090 kullan."])
        ctx.auto_capture(self.proj, ["Bundan sonra port 9090 kullan."])
        self.assertEqual(len(d.read_text().splitlines()), 1)

    def test_long_unpunctuated_talk_is_not_a_decision(self):
        talk = ("şimdi birde şu sıkıntı şimdi benim istediğim şu claude code tamamında bu sistemin çalışması yani ben "
                "bazen yeni bir sohbet açıyorum bilgisayar ayarlarında bişey yaptırmak istiyorum ama her zaman böyle olmuyor")
        self.assertEqual(ctx.auto_capture(self.proj, [talk]), 0)

    def test_common_words_are_not_decisions(self):
        self.assertEqual(ctx.auto_capture(self.proj, ["Artık uygulama açılmıyor, neden?", "Header kısmı bozuk görünüyor."]), 0)

    def test_long_key_upserts(self):
        k = "k" * 70
        run_io(ctx.cmd_decide, [f"{k}: a"])
        run_io(ctx.cmd_decide, [f"{k}: b"])
        lines = (self.proj / ".ctx" / "DECISIONS.md").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith(": b"))

    def test_turkish_capital_i(self):
        run_io(ctx.cmd_decide, ["dil: İngilizce"])
        run_io(ctx.cmd_decide, ["DİL: Türkçe"])
        self.assertEqual(len((self.proj / ".ctx" / "DECISIONS.md").read_text().splitlines()), 1)
        self.assertIn("Türkçe", run_io(ctx.cmd_recall, ["türkçe"])[1])
        run_io(ctx.cmd_decide, ["yer: İstanbul"])
        self.assertIn("İstanbul", run_io(ctx.cmd_recall, ["istanbul"])[1])

    def test_store_names_do_not_collide(self):
        a, b = self.t / "a" / "b-c", self.t / "a" / "b" / "c"
        self.assertNotEqual(ctx.store_root(a), ctx.store_root(b))

    def test_old_store_moves_to_hashed_name(self):
        f = self.t / "w"
        old = ctx.STORE / __import__("re").sub(r"[^A-Za-z0-9]", "-", str(f.resolve())).strip("-")
        (old / ".ctx").mkdir(parents=True)
        (old / ".ctx" / "RULES.md").write_text("- kural\n")
        new = ctx.store_root(f)
        self.assertTrue((new / ".ctx" / "RULES.md").exists())
        self.assertFalse(old.exists())


class Settings(Sandbox):
    """A1, A2, C11, C12, B10: trigger, effort and settings safety."""

    def test_init_removes_forced_low_effort_and_200k(self):
        sf = self.proj / ".claude" / "settings.json"
        sf.parent.mkdir()
        sf.write_text(json.dumps({"autoCompactWindow": 200000, "effortLevel": "low", "model": "opus",
                                  "env": {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "57", "X": "1"}}))
        run_io(ctx.cmd_init, [str(self.proj)])
        s = json.loads(sf.read_text())
        self.assertNotIn("effortLevel", s)
        self.assertNotIn("autoCompactWindow", s)
        self.assertEqual(s["env"], {"X": "1"})
        self.assertEqual(s["model"], "opus")
        self.assertIn("PreCompact", s["hooks"])

    def test_init_keeps_effort_the_user_asked_for(self):
        run_io(ctx.cmd_init, [str(self.proj), "--effort", "medium"])
        self.assertEqual(json.loads((self.proj / ".claude" / "settings.json").read_text())["effortLevel"], "medium")

    def test_init_refuses_home(self):
        self.assertEqual(run_io(ctx.cmd_init, [str(Path.home())])[0], 2)

    def test_trigger_leaves_real_work_room(self):
        pct = ctx.safe_pct(ctx.DEFAULT_WINDOW, ctx.DEFAULT_PCT, 91_396)
        self.assertGreaterEqual(ctx.DEFAULT_WINDOW * pct // 100 - 91_396, 120_000)

    def test_trigger_is_per_model_and_drops_top_level_200k(self):
        ctx.USER_SETTINGS.write_text(json.dumps({"autoCompactWindow": 200000,
                                                 "modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 400000, "x": 1}}}))
        run_io(ctx.cmd_trigger, [])
        s = json.loads(ctx.USER_SETTINGS.read_text())
        self.assertNotIn("autoCompactWindow", s)
        w = s["modelSettings"]["claude-sonnet-5-5"]["autoCompactWindow"]; self.assertTrue(ctx.MIN_WORK < w * 0.8 < 400000)
        self.assertEqual(s["modelSettings"]["claude-opus-5-5"]["x"], 1)

    def test_effective_trigger_reads_model_settings(self):
        ctx.USER_SETTINGS.write_text(json.dumps({"autoCompactWindow": 200000, "env": {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "80"},
                                                 "modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 400000}}}))
        self.assertEqual(ctx.effective_trigger(self.t / "none", "claude-opus-5-5"), (400000, 80))
        self.assertEqual(ctx.effective_trigger(self.t / "none", "claude-haiku-5-5"), (200000, 80))

    def test_broken_settings_are_never_overwritten(self):
        broken = '{"permissions": {"allow": ["Bash"]},}'
        ctx.USER_SETTINGS.write_text(broken)
        code, _ = run_io(ctx.main, ["global", "on"])
        self.assertEqual(code, 1)
        self.assertEqual(ctx.USER_SETTINGS.read_text(), broken)

    def test_off_twice_keeps_user_values(self):
        ctx.USER_SETTINGS.write_text(json.dumps({"autoCompactWindow": 300000, "env": {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "70"}}))
        for a in ("on", "on", "off", "off"):
            run_io(ctx.cmd_global, [a])
        s = json.loads(ctx.USER_SETTINGS.read_text())
        self.assertEqual((s.get("autoCompactWindow"), s.get("env", {}).get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE")), (300000, "70"))
        self.assertNotIn("modelSettings", s)


class Hooks(Sandbox):
    """A4 + D13-D15: spare folders, pause, guard, broken input."""

    def big(self, name="big.txt", data=b"x\n" * 5000):
        f = self.t / name
        f.write_bytes(data)
        return str(f)

    def guard(self, data, *args):
        return run_io(ctx.hook_guard, list(args), json.dumps(data))[1]

    def test_offset_with_limit_allowed_offset_alone_denied(self):
        f = self.big()
        self.assertEqual(self.guard({"tool_name": "Read", "tool_input": {"file_path": f, "offset": 10, "limit": 100}}), "")
        self.assertIn("offset AND limit", self.guard({"tool_name": "Read", "tool_input": {"file_path": f, "offset": 10}}))

    def test_binary_file_is_not_guarded(self):
        f = self.big("x.sqlite", b"SQLite format 3\0" + b"\1" * 40_000)
        self.assertEqual(self.guard({"tool_name": "Read", "tool_input": {"file_path": f}}), "")

    def test_quoted_cat_is_guarded(self):
        f = self.big("big file.txt")
        self.assertIn("deny", self.guard({"tool_name": "Bash", "tool_input": {"command": f"cat '{f}'"}}))
        self.assertEqual(self.guard({"tool_name": "Bash", "tool_input": {"command": f"cat '{f}' | head"}}), "")

    def test_broken_hook_input_returns_zero(self):
        for raw in ("", "null", "[]", '"s"', "{bad", '{"tool_name": "Read", "tool_input": "x"}',
                    '{"tool_name": "Read", "tool_input": {"file_path": "/nope", "limit": "abc"}}'):
            for fn in (ctx.hook_guard, ctx.hook_precompact, ctx.hook_session):
                self.assertEqual(run_io(fn, [], raw)[0], 0, (fn.__name__, raw))

    def test_bad_utf8_transcript(self):
        tp = self.t / "bad.jsonl"
        tp.write_bytes(b'{"x": "\xff"}\n' + json.dumps({"message": {"usage": {"input_tokens": 5}}}).encode() + b"\n")
        self.assertEqual(ctx.base_after_last_compact(tp), 5)

    def test_paused_session_steps_aside(self):
        f = self.big()
        run_io(ctx.cmd_pause, ["s1"])
        self.assertEqual(self.guard({"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": f}}), "")
        self.assertIn("deny", self.guard({"session_id": "s2", "tool_name": "Read", "tool_input": {"file_path": f}}))
        code, out = run_io(ctx.cmd_compact_summary, [], json.dumps({"session_id": "s1", "cwd": str(self.proj)}))
        self.assertEqual((code, out), (1, ""))
        run_io(lambda a: ctx.cmd_pause(a, on=False), ["s1"])
        self.assertIn("deny", self.guard({"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": f}}))

    def test_spare_folder_gets_no_memory(self):
        spare = str(Path.home() / ".claude" / "spares" / "spare-AbC123")
        ctx.GLOBAL_FLAG.parent.mkdir(parents=True)
        ctx.GLOBAL_FLAG.write_text('{"enabled": true}')
        self.assertEqual(run_io(ctx.hook_session, ["--global"], json.dumps({"cwd": spare}))[1], "")
        self.assertEqual(run_io(ctx.cmd_compact_summary, [], json.dumps({"cwd": spare, "session_id": "z"}))[0], 1)
        self.assertFalse(ctx.STORE.exists() and any(ctx.STORE.iterdir()))

    def test_status_finds_the_real_folder_transcript_in_global_mode(self):
        home = self.t / "home"
        real = self.t / "work"
        real.mkdir()
        d = home / ".claude" / "projects" / __import__("re").sub(r"[^A-Za-z0-9]", "-", str(real.resolve()))
        d.mkdir(parents=True)
        (d / "s.jsonl").write_text("{}\n")
        old = os.environ.get("HOME", "")
        os.environ["HOME"], os.environ["CLAUDE_PROJECT_DIR"] = str(home), str(real)
        try:
            self.assertEqual(ctx.find_transcript(ctx.STORE / "x"), d / "s.jsonl")
        finally:
            os.environ["HOME"] = old


class AutoInstall(unittest.TestCase):
    """A1 + D16: autoinstall.sh writes no effort level and skips ~/PROJECTS itself."""

    def run_auto(self, home, project_dir):
        env = {"HOME": str(home), "PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": str(project_dir)}
        return subprocess.run(["bash", str(REPO / "system" / "autoinstall.sh")], env=env, capture_output=True, text=True, timeout=60)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        repo = self.home / "PROJECTS" / "Last Token" / "system"
        repo.mkdir(parents=True)
        for f in ("ctx.py",):
            (repo / f).write_text((REPO / "system" / f).read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_project_without_effort(self):
        p = self.home / "PROJECTS" / "app"
        (p / ".git").mkdir(parents=True)
        self.run_auto(self.home, p)
        s = json.loads((p / ".claude" / "settings.json").read_text())
        self.assertNotIn("effortLevel", s)
        self.assertTrue((p / ".ctx" / "ctx.py").exists())

    def test_projects_root_itself_is_skipped(self):
        root = self.home / "PROJECTS"
        (root / ".git").mkdir()
        self.run_auto(self.home, str(root) + "/")
        self.assertFalse((root / ".ctx").exists())

    def test_old_install_is_migrated(self):
        p = self.home / "PROJECTS" / "old"
        (p / ".ctx").mkdir(parents=True)
        (p / ".ctx" / "ctx.py").write_text("# old\n")
        (p / ".claude").mkdir()
        (p / ".claude" / "settings.json").write_text(json.dumps({"effortLevel": "low", "autoCompactWindow": 200000}))
        self.run_auto(self.home, p)
        s = json.loads((p / ".claude" / "settings.json").read_text())
        self.assertNotIn("effortLevel", s)
        self.assertNotIn("autoCompactWindow", s)
        self.assertEqual((p / ".ctx" / "ctx.py").read_text(), (REPO / "system" / "ctx.py").read_text())


if __name__ == "__main__":
    unittest.main()


class RuleLists(unittest.TestCase):
    """A numbered rule list given in one call is kept whole, one rule per line (r18: R7–R10 were cut)."""

    def test_r_items_split(self):
        self.assertEqual(ctx.split_rules("R1 a b. R2 c. R10 d 2. e"), ["R1 a b.", "R2 c.", "R10 d 2. e"])

    def test_numbered_items_split(self):
        self.assertEqual(ctx.split_rules("1. tabs 2. no emoji"), ["1. tabs", "2. no emoji"])

    def test_plain_rule_untouched(self):
        self.assertEqual(ctx.split_rules("Port 8080 and 2. option"), ["Port 8080 and 2. option"])
