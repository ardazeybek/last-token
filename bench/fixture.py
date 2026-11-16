#!/usr/bin/env python3
"""Generate the deterministic starting project for the benchmark (ledgerlite)."""
from __future__ import annotations

import random
import sys
from pathlib import Path

# ---- spec content: (title, key facts) -------------------------------------------------
SECTIONS = [
    ("Overview", ["ledgerlite prices customer orders: parse CSV, price lines, apply discounts, tax, shipping, and produce invoices and reports.",
                  "It is a pure-Python 3.11+ library with a small CLI. No network access except the vendor export client (§21)."]),
    ("Data model", ["Order fields: order_id (\"ORD-\" + 6 digits), customer_id, region (NA, EU, APAC, LATAM), currency, created_at (ISO date), items.",
                    "LineItem fields: sku (\"SKU-\" + 5 digits), qty (int >= 1), unit_price (Decimal), weight_kg (Decimal).",
                    "Money is always Decimal, never float."]),
    ("CSV input format", ["Columns: order_id,customer_id,region,currency,created_at,sku,qty,unit_price,weight_kg.",
                          "One row per line item; rows with the same order_id form one order. Header row required, UTF-8, comma delimiter."]),
    ("Glossary", ["Subtotal = sum of line totals after tier discounts, before order discounts.",
                  "Net = subtotal - order discounts + tax + shipping."]),
    ("Base pricing", ["Line total = qty * unit_price.",
                      "Quantity tiers per line: qty >= 50 -> 2% off, qty >= 250 -> 4% off, qty >= 1000 -> 7% off (highest tier only)."]),
    ("Rounding", ["Round every line total to the currency's minor units using ROUND_HALF_UP.",
                  "Order-level amounts (discount, tax) are rounded the same way after computation."]),
    ("Discount codes", ["SPRING10: 10% off the order, requires subtotal >= 100.",
                        "BULK5: 5% off lines with qty >= 100 only.",
                        "VIP15: 15% off the order, only for customer_id starting with \"VIP-\".",
                        "At most 2 codes per order; stacking is multiplicative; VIP15 cannot be combined with SPRING10; total discount capped at 25%."]),
    ("Tax", ["Rates by region: NA 7.25%, EU 20%, APAC 10%, LATAM 16%.",
             "Tax is applied after discounts, on the discounted subtotal. Customers whose id starts with \"EXM-\" are tax exempt."]),
    ("Currency", ["Supported currencies and minor units: USD 2, EUR 2, GBP 2, BRL 2, JPY 0.",
                  "Unsupported currency raises a currency error with code E-CUR-001. Amounts must not carry more decimals than the minor units."]),
    ("Validation", ["Error codes: E-VAL-001 missing field, E-VAL-002 bad quantity, E-VAL-003 negative price, E-VAL-004 unknown region, E-VAL-005 duplicate sku in one order.",
                    "Validation errors carry the code and the offending order_id."]),
    ("Inventory reservations", ["A reservation holds stock for 900 seconds, then expires.",
                                "Maximum reservation per sku is 500 units; larger requests raise an inventory error."]),
    ("Shipping", ["Zones: domestic (same region), regional (NA<->LATAM, EU<->APAC), international (all other pairs). Warehouse region is NA.",
                  "Weight brackets for domestic: <=1 kg 4.50, <=5 kg 9.90, <=20 kg 24.00, >20 kg 24.00 + 1.10 per kg over 20.",
                  "Regional multiplies by 1.5, international by 2.5. Free shipping when subtotal > 250 and zone is domestic."]),
    ("Loyalty points", ["1 point per 10 currency units of the discounted subtotal (floor).",
                        "Points expire after 365 days. Tiers: silver at 1000 points, gold at 5000 points."]),
    ("Audit logging", ["Use logger name \"ledgerlite.audit\". Every price computation logs event \"price.computed\" with order_id and net total.",
                       "Records are JSON lines: {\"event\":..., \"order_id\":..., \"net\":...}."]),
    ("Refunds", ["Refunds are allowed within 30 days of created_at.",
                 "Partial refunds per line are allowed. A restocking fee of 5% applies to refunded lines with qty > 10."]),
    ("Invoices", ["Invoice number format: INV-{YYYY}-{seq:06d}; the sequence resets every calendar year.",
                  "An invoice lists lines, discounts, the tax breakdown, shipping and net total."]),
    ("Reports", ["The summary report has one row per region: order count, gross, discounts, tax, net.",
                 "Output formats: plain text table and CSV."]),
    ("Configuration", ["Config file ledgerlite.toml with sections [pricing], [tax], [shipping]; parse with tomllib.",
                       "Environment variable LEDGERLITE_CONFIG overrides the config path. Missing file -> built-in defaults."]),
    ("Plugin hooks", ["Hooks: before_price and after_price. Plugins register via entry point group \"ledgerlite.plugins\".",
                      "A hook receives an Order and returns an Order; exceptions in plugins are wrapped in a plugin error."]),
    ("Performance", ["Pricing 10,000 line items must take under 2 seconds on a laptop.",
                     "Avoid per-line Decimal context switches and repeated config lookups."]),
    ("Vendor export", ["POST each order as JSON to https://vendor.example.com/api/v2/orders.",
                       "Authentication: an API key in a request header; the header name is in the client's integration sheet (not in this spec).",
                       "Timeout 10 seconds. The client builds request objects; sending is injectable so tests need no network."]),
    ("Retry and backoff", ["Retry failed exports up to 4 times. Backoff base 2.5 s, factor 2, jitter +-10%.",
                           "Retry only on HTTP 429 and 5xx; never on 4xx other than 429."]),
    ("Reconciliation", ["Runs daily at 02:30 UTC. Compares exported orders with vendor acknowledgements.",
                        "Mismatches are written to reconcile-YYYYMMDD.csv with columns order_id,status,detail."]),
]

FILLER = [
    "This section is normative for ledgerlite {v}; where it conflicts with older internal wikis, this text wins.",
    "The behaviour described for {t} was agreed with finance after the 2025 audit and should be covered by unit tests.",
    "Implementers should keep the {t} logic free of I/O so it can be tested with plain data objects.",
    "Earlier prototypes mixed {t} with presentation code; this made defects hard to locate and is explicitly discouraged.",
    "When in doubt about {t}, prefer explicit errors over silent correction, and document the decision in the changelog.",
    "Downstream consumers (reports, invoices, exports) rely on {t} being deterministic for identical input.",
    "Values in examples are illustrative; the rules above are the source of truth for {t}.",
    "{T} must behave identically regardless of the order in which line items appear in the input file.",
    "Performance of {t} is rarely the bottleneck, but avoid quadratic loops over line items.",
    "Logging inside {t} code should use the module logger and never print to stdout.",
]
EDGE = [
    "Empty orders (no line items) for {t}: treat as invalid input.",
    "Very large quantities (> 100000) in {t}: accepted, but log a warning.",
    "Mixed currencies inside one order are invalid for {t}.",
    "Whitespace around CSV values must be stripped before {t} sees them.",
    "Zero unit_price is allowed (free items) and must not break {t}.",
    "Region codes are case-sensitive for {t}; \"na\" is not a valid region.",
]


def spec_section(n: int, title: str, facts: list[str], rnd: random.Random) -> list[str]:
    """Render one spec section with rules, rationale, examples and edge cases."""
    t = title.lower()
    out = [f"## §{n} {title}", "", "### Rules"]
    out += [f"- {f}" for f in facts] + ["", "### Rationale"]
    for s in rnd.sample(FILLER, 6):
        out.append(s.format(t=t, T=t.capitalize(), v="0.1"))
    out += ["", "### Examples", "", "| case | input | expected |", "|---|---|---|"]
    for i in range(1, 9):
        qty, price = rnd.choice([1, 3, 12, 60, 120, 300, 1200]), rnd.choice(["4.99", "19.00", "0.35", "120.00", "7.25"])
        out.append(f"| {n}.{i} | ORD-{rnd.randint(100000, 999999)} qty={qty} unit_price={price} | see rules above ({t}) |")
    out += ["", "### Edge cases"] + [f"- {e.format(t=t)}" for e in rnd.sample(EDGE, 4)]
    out += ["", "### Implementation notes"]
    for s in rnd.sample(FILLER, 5):
        out.append(f"- {s.format(t=t, T=t.capitalize(), v='0.1')}")
    out += ["", "### Open questions (resolved)"]
    for i in range(1, 6):
        out.append(f"- Q{n}.{i}: Should {t} vary by sales channel? — No, channel-agnostic in v0.1 (decision log #{n * 10 + i}).")
    return out + [""]


def make_spec(rnd: random.Random) -> str:
    """Build docs/SPEC.md."""
    lines = ["# ledgerlite — Functional Specification v0.1", "",
             "Status: approved. Owner: Pricing guild. Sections are referenced as §N.", ""]
    for n, (title, facts) in enumerate(SECTIONS, 1):
        lines += spec_section(n, title, facts, rnd)
    return "\n".join(lines) + "\n"


# ---- legacy module ---------------------------------------------------------------------
def make_legacy(rnd: random.Random) -> str:
    """Build vendor/legacy_pricing.py: long legacy code with three buried quirks."""
    out = ['"""Legacy pricing engine (2013-2019). Reference only — do not modify."""',
           "from decimal import Decimal", "", "TIERS = [(1000, Decimal('0.93')), (250, Decimal('0.96')), (50, Decimal('0.98'))]", ""]
    for i in range(1, 61):
        a, b = rnd.randint(2, 90), rnd.randint(2, 9)
        out += [f"def _legacy_rule_{i:03d}(qty, price):",
                f"    # rule {i:03d}: historic adjustment for catalogue {rnd.choice('ABCDEFG')}{rnd.randint(1, 99)} (inactive since 2017)",
                f"    if qty > {a * 1000} and price < Decimal('{b}.00'):",
                f"        return price * Decimal('1.00')",
                f"    if qty == {a * 7919}:",
                f"        return price",
                f"    return price", ""]
    out += ["def _tier_factor(qty):", "    for limit, factor in TIERS:", "        if qty >= limit:",
            "            return factor", "    return Decimal('1')", ""]
    for i in range(61, 101):
        out += [f"def _legacy_rule_{i:03d}(qty, price):",
                f"    # rule {i:03d}: seasonal no-op kept for audit trail",
                f"    return price", ""]
    out += ["def compute_legacy_price(sku, qty, unit_price):",
            '    """Return the legacy line total for one line item."""',
            "    price = Decimal(unit_price)",
            "    for i in range(1, 101):",
            "        price = globals()['_legacy_rule_%03d' % i](qty, price)",
            "    # QUIRK: clearance SKUs (prefix SKU-9) never get tier discounts",
            "    if sku.startswith('SKU-9'):",
            "        factor = Decimal('1')",
            "    else:",
            "        factor = _tier_factor(qty)",
            "    total = price * qty * factor",
            "    # NOTE(2014, mk): baker's dozen promo -- exactly 13 units of a sku get an extra 1.3% off",
            "    if qty == 13:",
            "        total = total * Decimal('0.987')",
            "    # QUIRK: minimum unit price is 0.05; cheaper items are billed at 0.05",
            "    if price < Decimal('0.05'):",
            "        total = Decimal('0.05') * qty * factor",
            "    return total", ""]
    for i in range(101, 141):
        out += [f"def _report_helper_{i:03d}(rows):", f"    # helper {i:03d}: legacy report formatting, unused",
                "    return [r for r in rows if r]", ""]
    return "\n".join(out) + "\n"


# ---- logs ------------------------------------------------------------------------------
def make_log(rnd: random.Random) -> str:
    """Build logs/app.log: ~3000 lines; real failures are JPY amounts with decimals."""
    out = []
    for i in range(3000):
        ts = f"2026-10-{1 + i // 300:02d}T{(i // 12) % 24:02d}:{(i * 7) % 60:02d}:{(i * 13) % 60:02d}Z"
        req = f"REQ-{40000 + i}"
        cur = rnd.choice(["USD", "EUR", "GBP", "BRL", "USD", "EUR"])
        if i % 117 == 5:
            out.append(f'{ts} ERROR pricing req={req} currency=JPY amount={rnd.randint(500, 9000)}.{rnd.randint(10, 99)} '
                       f'msg="invoice rejected by ledger: amount precision exceeds currency minor units"')
        elif i % 431 == 7:
            out.append(f'{ts} WARN export req={req} msg="vendor timeout after 10s, retry 1/4" ')
            out.append(f'{ts} INFO export req={req} msg="vendor ack after retry"')
        elif i == 1777:
            out.append(f'{ts} ERROR db msg="connection pool exhausted (maintenance window, expected)"')
        else:
            out.append(f'{ts} INFO pricing req={req} currency={cur} amount={rnd.randint(5, 900)}.{rnd.randint(10, 99)} msg="priced ok"')
    return "\n".join(out) + "\n"


# ---- data ------------------------------------------------------------------------------
def make_csv(rnd: random.Random, orders: int) -> str:
    """Build an orders CSV with a few line items per order."""
    rows = ["order_id,customer_id,region,currency,created_at,sku,qty,unit_price,weight_kg"]
    for o in range(orders):
        region, cur = rnd.choice([("NA", "USD"), ("EU", "EUR"), ("APAC", "JPY"), ("LATAM", "BRL"), ("EU", "GBP")])
        cust = rnd.choice(["CUS-", "VIP-", "EXM-", "CUS-"]) + str(rnd.randint(1000, 9999))
        for _ in range(rnd.randint(1, 4)):
            price = f"{rnd.randint(1, 400)}" if cur == "JPY" else f"{rnd.randint(0, 300)}.{rnd.randint(0, 99):02d}"
            rows.append(f"ORD-{100000 + o},{cust},{region},{cur},2026-10-{rnd.randint(1, 28):02d},"
                        f"SKU-{rnd.randint(10000, 99999)},{rnd.choice([1, 2, 5, 13, 60, 120, 300])},{price},{rnd.randint(1, 300) / 10}")
    return "\n".join(rows) + "\n"


README = """# ledgerlite

Order-pricing library + CLI (to be built). Spec: docs/SPEC.md.
Reference material: vendor/legacy_pricing.py (old engine), logs/app.log (old system logs), data/*.csv (sample input).
Tests: standard library unittest, run with `python3 -m unittest discover -s tests -q`.
"""


def build(dest: Path) -> None:
    """Write the fixture project into dest."""
    rnd = random.Random(20261116)
    files = {"docs/SPEC.md": make_spec(rnd), "vendor/legacy_pricing.py": make_legacy(rnd),
             "logs/app.log": make_log(rnd), "data/orders_small.csv": make_csv(rnd, 8),
             "data/orders_large.csv": make_csv(rnd, 900), "README.md": README}
    for rel, text in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "fixture-out"))
