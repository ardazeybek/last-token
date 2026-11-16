#!/usr/bin/env python3
"""Score a finished benchmark run: tokens, context fill, rule compliance, recall, tests.

usage: score.py RUN_DIR [--out results/x.json]      score one run
       score.py --table results/*.json               print markdown tables
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fixture  # noqa: E402
from steps import STEPS, TRUTH  # noqa: E402

WINDOW = 200_000
ALLOWED_NUMS = {0, 1, 2, 100}
LATE_MODULES = {"report", "config", "plugins", "vendor_export", "cli", "reconcile"}


# ---- rule checks -------------------------------------------------------------------
def functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """All function and method definitions in a module."""
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def annotated(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when all parameters (except self/cls) and the return value are annotated."""
    a = fn.args
    params = a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]
    params = [p for p in params if p.arg not in ("self", "cls")]
    return fn.returns is not None and all(p.annotation is not None for p in params)


def bad_numbers(tree: ast.AST) -> int:
    """Count numeric literals outside the allowed set."""
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float) and node.value not in ALLOWED_NUMS:
            n += 1
    return n


def error_classes(src: Path) -> set[str]:
    """Class names defined in errors.py."""
    f = src / "errors.py"
    if not f.exists():
        return set()
    return {n.name for n in ast.walk(ast.parse(f.read_text())) if isinstance(n, ast.ClassDef)}


def raise_ok(node: ast.Raise, allowed: set[str]) -> bool:
    """True when a raise uses an errors.py class (or re-raises a variable)."""
    exc = node.exc
    if exc is None:
        return True
    target = exc.func if isinstance(exc, ast.Call) else exc
    name = target.attr if isinstance(target, ast.Attribute) else target.id if isinstance(target, ast.Name) else ""
    return name in allowed or not name[:1].isupper()  # helpers/variables returning errors are fine


def ratio(ok: int, total: int) -> float:
    """Pass ratio, 1.0 when nothing to check."""
    return round(ok / total, 3) if total else 1.0


def check_modules(src: Path, tests: Path, names: set[str] | None = None) -> dict:
    """Rules R1–R8 over src/ledgerlite modules (optionally restricted to names)."""
    allowed = error_classes(src)
    c = {k: [0, 0] for k in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8")}
    for f in sorted(src.glob("*.py")):
        if names is not None and f.stem not in names:
            continue
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        fns = functions(tree)
        add(c, "R1", ast.get_docstring(tree) is not None)
        for fn in fns:
            add(c, "R2", ast.get_docstring(fn) is not None)
            add(c, "R3", annotated(fn))
            add(c, "R5", (fn.end_lineno or fn.lineno) - fn.lineno + 1 <= 40)
        if f.name != "cli.py":
            add(c, "R4", not any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "print" for n in ast.walk(tree)))
        if f.name != "constants.py":
            add(c, "R6", bad_numbers(tree) == 0)
        if f.stem not in ("__init__", "constants", "errors"):
            add(c, "R7", (tests / f"test_{f.stem}.py").exists())
        for n in ast.walk(tree):
            if isinstance(n, ast.Raise):
                add(c, "R8", raise_ok(n, allowed))
    return {k: ratio(*v) for k, v in c.items()}


def add(c: dict, key: str, ok: bool) -> None:
    """Increment a pass/total counter."""
    c[key][0] += int(ok)
    c[key][1] += 1


def check_changelog(work: Path) -> float:
    """R9: share of steps with a '- step N:' changelog line."""
    f = work / "CHANGELOG.md"
    if not f.exists():
        return 0.0
    found = {int(m) for m in re.findall(r"step\s*(\d+)", f.read_text(), flags=re.I)}
    return ratio(len(found & set(range(1, len(STEPS) + 1))), len(STEPS))


def check_vendor(work: Path) -> float:
    """R10: vendor/ identical to the fixture."""
    with tempfile.TemporaryDirectory() as t:
        fixture.build(Path(t))
        ref = (Path(t) / "vendor" / "legacy_pricing.py").read_text()
    files = list((work / "vendor").rglob("*")) if (work / "vendor").exists() else []
    cur = work / "vendor" / "legacy_pricing.py"
    same = cur.exists() and cur.read_text() == ref and len([f for f in files if f.is_file() and "__pycache__" not in str(f)]) == 1
    return 1.0 if same else 0.0


# ---- recall ------------------------------------------------------------------------
def check_recall(work: Path) -> dict:
    """Score ANSWERS.json against ground truth, plus whether decisions reached the code."""
    try:
        ans = {k.lower(): str(v).lower() for k, v in json.loads((work / "ANSWERS.json").read_text()).items()}
    except (OSError, ValueError, AttributeError):
        ans = {}
    per = {}
    for key, (accepted, _step, _kind) in TRUTH.items():
        v = ans.get(key, "")
        ok = any(a in v for a in accepted)
        if key == "report_sort":
            ok = ok and ("net" in v or "total" in v) and "desc" in v
        per[key] = ok
    code = "\n".join(p.read_text(errors="replace") for p in (work / "src").rglob("*.py")) if (work / "src").exists() else ""
    notes = (work / "RELEASE_NOTES.md").read_text().lower() if (work / "RELEASE_NOTES.md").exists() else ""
    pyproject = (work / "pyproject.toml").read_text() if (work / "pyproject.toml").exists() else ""
    applied = {"rounding_half_even": "ROUND_HALF_EVEN" in code, "refund_45": bool(re.search(r"\b45\b", code)),
               "vendor_header": "X-Vendor-Token" in code, "dev_port": "8743" in code,
               "cli_name": bool(re.search(r"^\s*llite\s*=", pyproject, re.M)),
               "notes_codename": "copperfield" in notes, "notes_contact": "dana whitfield" in notes}
    return {"answers": per, "recall": ratio(sum(per.values()), len(per)),
            "applied": applied, "applied_score": ratio(sum(applied.values()), len(applied))}


def run_tests(work: Path) -> dict:
    """Run the project's unittest suite."""
    try:
        p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=work,
                           env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=600)
        out = p.stderr + p.stdout
    except subprocess.TimeoutExpired:
        return {"ran": 0, "ok": False}
    m = re.search(r"Ran (\d+) test", out)
    return {"ran": int(m.group(1)) if m else 0, "ok": p.returncode == 0}


# ---- tokens ------------------------------------------------------------------------
def token_stats(state: dict) -> dict:
    """Totals from the cumulative per-session modelUsage, plus context statistics."""
    last_usage = {}
    for s in state["steps"]:
        if s.get("session_model_usage"):
            last_usage[s["session"]] = (s["session_model_usage"], s.get("session_cost_usd") or 0)
    tot = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    cost = 0.0
    for mu, c in last_usage.values():
        cost += c
        for m in mu.values():
            tot["input"] += m.get("inputTokens", 0)
            tot["output"] += m.get("outputTokens", 0)
            tot["cache_read"] += m.get("cacheReadInputTokens", 0)
            tot["cache_write"] += m.get("cacheCreationInputTokens", 0)
    calls = [c for s in state["steps"] for c in s.get("calls", [])]
    peak = max((s["max_ctx"] for s in state["steps"]), default=0)
    first60 = next((s["step"] for s in state["steps"] if s["max_ctx"] >= 0.6 * WINDOW), None)
    comps = sum(len(v) for v in state.get("compactions", {}).values())
    return {"total_tokens": sum(tot.values()), **tot, "cost_usd": round(cost, 4),
            "peak_ctx": peak, "peak_fill": round(peak / WINDOW, 3), "first_step_60pct": first60,
            "mean_ctx_per_call": int(sum(calls) / len(calls)) if calls else 0, "api_calls": len(calls),
            "compactions": comps, "new_chats": len(state["sessions"]) - 1,
            "errors": sum(1 for s in state["steps"] if s.get("is_error")),
            "wall_min": round(sum(s["secs"] for s in state["steps"]) / 60, 1)}


def score(run_dir: Path) -> dict:
    """Score one run directory."""
    state = json.loads((run_dir / "state.json").read_text())
    work = run_dir / "work"
    src, tests = work / "src" / "ledgerlite", work / "tests"
    rules = check_modules(src, tests) if src.exists() else {}
    rules["R9"] = check_changelog(work)
    rules["R10"] = check_vendor(work)
    late = check_modules(src, tests, LATE_MODULES) if src.exists() else {}
    return {"run": str(run_dir), "cond": state["cond"], "model": state["model"], "pct": state.get("pct"),
            "steps_done": len(state["steps"]), **token_stats(state),
            "rules": rules, "rule_score": round(sum(rules.values()) / 10, 3),
            "late_rules": late, "late_rule_score": round(sum(late.values()) / max(len(late), 1), 3),
            **check_recall(work), "tests": run_tests(work)}


# ---- table -------------------------------------------------------------------------
def table(files: list[str]) -> str:
    """Markdown summary table of scored runs."""
    rows = [json.loads(Path(f).read_text()) for f in files]
    head = ("| run | cond | total tokens | cost $ | peak fill | step ≥60% | mean ctx/call | calls | compactions | new chats "
            "| rules | late rules | recall | applied | tests |")
    out = [head, "|" + "---|" * 15]
    for r in rows:
        t = r["tests"]
        out.append(f"| {Path(r['run']).parent.name}/{Path(r['run']).name} | {r['cond']} | {r['total_tokens']:,} | {r['cost_usd']} "
                   f"| {r['peak_fill']:.0%} | {r['first_step_60pct'] or '—'} | {r['mean_ctx_per_call']:,} | {r['api_calls']} "
                   f"| {r['compactions']} | {r['new_chats']} | {r['rule_score']:.0%} | {r['late_rule_score']:.0%} "
                   f"| {r['recall']:.0%} | {r['applied_score']:.0%} | {t['ran']} {'ok' if t['ok'] else 'FAIL'} |")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    """CLI entry."""
    if argv and argv[0] == "--table":
        print(table(argv[1:]))
        return 0
    res = score(Path(argv[0]).resolve())
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k not in ("rules", "late_rules", "answers", "applied")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
