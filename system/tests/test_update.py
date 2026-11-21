"""Self-update tests: a fake GitHub remote, a fake install.sh and a fake `claude` CLI. Run: python3 -m unittest discover system/tests"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

CTX = Path(__file__).resolve().parents[1] / "ctx.py"


def sh(*cmd, cwd=None):
    """Run a git/shell step quietly; fail the test on error."""
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


class SelfUpdate(unittest.TestCase):
    def setUp(self):
        # Fake remote with an install.sh, cloned as ~/.claude/last-token/src
        self.tmp = Path(tempfile.mkdtemp())
        self.home, self.origin, self.bin = self.tmp / "lt", self.tmp / "origin", self.tmp / "bin"
        self.home.mkdir(); self.bin.mkdir()
        sh("git", "init", "-q", "-b", "master", str(self.origin))
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            sh("git", "-C", str(self.origin), "config", k, v)
        self.commit("install.sh", "exit 0\n")
        sh("git", "clone", "-q", str(self.origin), str(self.home / "src"))
        shutil.copy(CTX, self.home / "ctx.py")
        # Fake claude CLI: records that a repair session was opened
        (self.bin / "claude").write_text(f"#!/bin/sh\necho \"$@\" > {self.tmp}/repaired\n")
        (self.bin / "claude").chmod(0o755)
        for tool in ("git", "bash", "sh"):
            (self.bin / tool).symlink_to(shutil.which(tool) or "/bin/" + tool)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def commit(self, name, body):
        """Add one commit to the fake remote."""
        (self.origin / name).write_text(body)
        sh("git", "-C", str(self.origin), "add", "-A")
        sh("git", "-C", str(self.origin), "commit", "-q", "-m", name)

    def update(self, *args):
        """Run `ctx.py self-update` against the fake home; return its stdout."""
        py = os.path.dirname(shutil.which("python3") or "/usr/bin/python3")
        env = {"PATH": f"{self.bin}:{py}", "CTX_HOME": str(self.home), "HOME": str(self.tmp)}
        r = subprocess.run(["/usr/bin/env", "python3", str(self.home / "ctx.py"), "self-update", *args], env=env,
                           capture_output=True, text=True, timeout=60)
        return r.stdout

    def test_up_to_date(self):
        self.assertIn("up to date", self.update())
        self.assertIn("at", json.loads((self.home / "update.json").read_text()))

    def test_new_version_is_pulled_and_failure_opens_one_repair(self):
        # Doctor fails in the fake home (no hooks) -> repair session, but only once per commit
        self.commit("NEW", "v2\n")
        out = self.update()
        self.assertTrue((self.home / "src" / "NEW").exists(), "new commit pulled")
        self.assertIn("repair session started", out)
        for _ in range(30):
            if (self.tmp / "repaired").exists():
                break
            time.sleep(0.1)
        self.assertIn("Install the latest Last Token", (self.tmp / "repaired").read_text())
        self.assertIn("repair skipped", self.update("--force"))

    def test_opt_out(self):
        # update_check never starts anything when auto is false
        (self.home / "update.json").write_text('{"auto": false}')
        code = ("import sys; sys.path.insert(0, %r); import ctx; ctx.update_check(); "
                "print(open(%r).read())") % (str(self.home), str(self.home / "update.json"))
        r = subprocess.run(["python3", "-c", code], env={**os.environ, "CTX_HOME": str(self.home)},
                           capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout), {"auto": False})


if __name__ == "__main__":
    unittest.main()
