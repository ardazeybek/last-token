"""Benchmark script: 32 user turns, the 10 house rules, and recall ground truth."""

RULES = """House rules (apply to ALL code in this project, for the whole project):
R1. Every Python module under src/ledgerlite/ starts with a one-line module docstring.
R2. Every function and method has a docstring.
R3. All function parameters (except self/cls) and all return values have type hints.
R4. No print() calls in src/ledgerlite/ except in cli.py.
R5. No function longer than 40 lines.
R6. Numeric literals other than 0, 1, -1, 2 and 100 must not appear in src/ledgerlite/ modules other than constants.py; put them in constants.py as UPPER_CASE names.
R7. Every module src/ledgerlite/<name>.py (except __init__.py, constants.py, errors.py) has a test file tests/test_<name>.py (stdlib unittest).
R8. Only raise exceptions defined in src/ledgerlite/errors.py (all subclass LedgerError).
R9. After every step, append a line to CHANGELOG.md: "- step <N>: <what changed>".
R10. Never modify anything under vendor/ (read-only reference)."""

STEPS = [
    # 1
    "Step 1. We are building ledgerlite (see README.md and docs/SPEC.md). " + RULES +
    "\nFact from the client: our contact person is Dana Whitfield.\n"
    "Task: create the package skeleton: src/ledgerlite/__init__.py, src/ledgerlite/errors.py (LedgerError base class "
    "plus subclasses you will need), src/ledgerlite/constants.py, tests/ and CHANGELOG.md.",
    "Step 2. Implement src/ledgerlite/models.py with the data model from spec §2 (dataclasses), with tests.",
    "Step 3. Implement src/ledgerlite/parser.py: parse the CSV format of spec §3 into Order objects (use data/orders_small.csv "
    "in a test). Also, so you know: our dev server will run on port 8743.",
    "Step 4. Study vendor/legacy_pricing.py and write docs/legacy_notes.md: the pricing rules it implements, including every quirk.",
    "Step 5. Implement src/ledgerlite/pricing.py: line totals and quantity tiers (spec §5), plus the legacy quirks you found, with tests.",
    "Step 6. Implement rounding (spec §6) in pricing. Important client decision: use banker's rounding (ROUND_HALF_EVEN), "
    "NOT the ROUND_HALF_UP written in the spec.",
    "Step 7. logs/app.log is from the old system. Find which requests failed and the root cause; write docs/incident.md.",
    "Step 8. Implement src/ledgerlite/discounts.py: discount codes and stacking rules of spec §7, with tests.",
    "Step 9. Implement src/ledgerlite/tax.py per spec §8, with tests. FYI for later: the vendor API authenticates with "
    "the request header X-Vendor-Token.",
    "Step 10. Implement src/ledgerlite/currency.py per spec §9 and make sure the root cause from the incident in step 7 "
    "cannot happen in our code. We agreed the CLI command will be called `llite`.",
    "Step 11. Implement src/ledgerlite/validation.py with the error codes of spec §10, with tests.",
    "Step 12. Implement src/ledgerlite/inventory.py (reservations, spec §11), with tests. Note: the refund window was "
    "negotiated with the client to 45 days (the spec says 30).",
    "Step 13. Run the whole test suite, fix any failures, and give me a 3-line status.",
    "Step 14. Implement src/ledgerlite/shipping.py per spec §12, with tests.",
    "Step 15. Implement src/ledgerlite/loyalty.py per spec §13, with tests. The release codename for v0.1 is "
    "'Copperfield'; do not put it in code, just remember it for the release notes at the end.",
    "Step 16. Add an end-to-end integration test that parses data/orders_large.csv and prices every order "
    "(parse, price, discounts, tax). Tell me the number of orders and the total net per region.",
    "Step 17. Implement src/ledgerlite/audit.py: audit logging per spec §14, and call it from pricing; with tests.",
    "Step 18. Implement src/ledgerlite/refunds.py per spec §15 using the refund window we negotiated; with tests.",
    "Step 19. Implement src/ledgerlite/invoices.py per spec §16, with tests.",
    "Step 20. Dana asked: summary reports must be sorted by region, then by net total descending. Implement "
    "src/ledgerlite/report.py per spec §17 with that ordering; with tests.",
    "Step 21. Refactor pricing.py and discounts.py: split any function longer than 25 lines; keep tests green.",
    "Step 22. Implement src/ledgerlite/config.py per spec §18 (tomllib), with tests.",
    "Step 23. Implement src/ledgerlite/plugins.py: the plugin hooks of spec §19, with tests.",
    "Step 24. Check the performance requirement of spec §20 with a quick timing of pricing 10,000 line items; optimise if needed.",
    "Step 25. Implement src/ledgerlite/vendor_export.py per spec §21: build request objects (no real network; injectable "
    "sender) and use the auth header name I gave you earlier; with tests.",
    "Step 26. Implement src/ledgerlite/cli.py with argparse: commands price, report, refund and serve (serve defaults to "
    "the dev server port I told you about). Register the console script in pyproject.toml under the command name we agreed; with tests.",
    "Step 27. Add retry with backoff to the vendor export per spec §22, with tests (no real sleeping in tests).",
    "Step 28. Add a --json output option to every CLI command; with tests.",
    "Step 29. Implement src/ledgerlite/reconcile.py per spec §23, with tests.",
    "Step 30. Write RELEASE_NOTES.md for v0.1: include the release codename and our client contact, and list the features.",
    "Step 31. Write ANSWERS.json with exactly these keys, using what we decided in THIS project (a client decision overrides "
    "the spec): contact, dev_port, rounding_mode, vendor_header, refund_window_days, codename, failing_currency, "
    "dozen_discount_pct (the extra discount percent the legacy engine gives for exactly 13 units), cli_name, report_sort. "
    "Values: short strings or numbers.",
    "Step 32. Run the full test suite, fix any failures, and finish the changelog.",
]

# recall ground truth: key -> (accepted normalised substrings, step where it was introduced, kind)
TRUTH = {
    "contact": (["dana whitfield"], 1, "chat"),
    "dev_port": (["8743"], 3, "chat"),
    "rounding_mode": (["half_even", "half even", "banker"], 6, "chat-override"),
    "vendor_header": (["x-vendor-token"], 9, "chat"),
    "refund_window_days": (["45"], 12, "chat-override"),
    "codename": (["copperfield"], 15, "chat"),
    "failing_currency": (["jpy"], 7, "derived-log"),
    "dozen_discount_pct": (["1.3"], 4, "derived-code"),
    "cli_name": (["llite"], 10, "chat"),
    "report_sort": (["region"], 20, "chat"),  # plus "net"/"total" + "desc" checked in score.py
}

NEW_CHAT_BRIEF = ("We are continuing work on an existing project in this directory: ledgerlite (see README.md, "
                  "docs/SPEC.md, CHANGELOG.md and the code). " + RULES +
                  "\nLook around the repository as needed to get oriented, then do the following.\n\n")
