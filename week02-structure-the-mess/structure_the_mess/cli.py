"""Command line entry point.

    python -m structure_the_mess.cli statement.pdf --db data/net.duckdb

Add --no-llm to run purely on the deterministic alias table (no API key
needed), or --compare to run both and report where they disagree.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extract import extract_pdf
from .load import dependents_of, load
from .normalize import normalize
from .report import write_report
from .schema import Filing
from .validate import compare_normalizers, run_checks, summarize


def _records(con, query: str) -> list[dict]:
    """Run a query and return plain dicts - no pandas required."""
    rel = con.sql(query)
    columns = rel.columns
    return [dict(zip(columns, row)) for row in rel.fetchall()]


def build_filing(
    pdf_path: str, use_llm: bool, company: str, ticker: str
) -> tuple[Filing, list]:
    rows, periods = extract_pdf(pdf_path)
    if not rows:
        raise SystemExit(f"No tabular data found in {pdf_path}")
    items, quarantined = normalize(rows, use_llm=use_llm)
    filing = Filing(
        company=company,
        ticker=ticker,
        fiscal_period=periods[-1],
        source_file=Path(pdf_path).name,
        periods=periods,
        line_items=items,
        quarantined=quarantined,
    )
    return filing, rows


def trace_key(filing: Filing, con, key: str) -> None:
    """Show where one figure came from and what depends on it.

    Crosschecking a derived number means answering two questions: what was
    literally printed on the page, and what else moves if this is wrong.
    Both are answerable from the stored data - no re-parsing, no guessing.
    """
    items = [li for li in filing.line_items if li.canonical_key == key]
    if not items:
        import difflib

        known = sorted({li.canonical_key for li in filing.line_items})
        close = difflib.get_close_matches(key, known, n=6, cutoff=0.4)
        print(f"\nNo canonical key '{key}'.")
        if close:
            print("Did you mean: " + ", ".join(close))
        else:
            print(f"{len(known)} keys available; try --trace with one of them.")
        return

    order = {p: i for i, p in enumerate(filing.periods)}
    items.sort(key=lambda li: (li.statement.value, order.get(li.period, 99)))

    print(f"\n{'=' * 78}\nTRACE  {key}\n{'=' * 78}")
    stmts = sorted({li.statement.value for li in items})
    units = sorted({li.unit.value for li in items})
    methods = sorted({li.normalization_method for li in items})
    conf = min(li.normalization_confidence for li in items)
    print(f"  statement(s): {', '.join(stmts)}")
    print(f"  unit(s):      {', '.join(units)}")
    print(f"  normalized by {', '.join(methods)} (min confidence {conf:.2f})")

    print(f"\n  {'period':10} {'value':>16}  {'page':>4}  label")
    print(f"  {'-' * 10} {'-' * 16}  {'-' * 4}  {'-' * 40}")
    for li in items:
        val = "—" if li.value is None else f"{li.value:,.2f}".rstrip("0").rstrip(".")
        print(f"  {li.period:10} {val:>16}  {li.page:>4}  {li.label[:48]}")

    sources = sorted({li.source_line for li in items if li.source_line})
    if sources:
        print("\n  verbatim source line(s) from the PDF:")
        for src in sources:
            print(f"    {src[:150]}")

    deps = dependents_of(key)
    if deps:
        print("\n  derived metrics built from this key:")
        for col in deps:
            view, column = col.split(".")
            try:
                rel = con.sql(
                    f"SELECT period, {column} FROM {view} ORDER BY period_sort"
                )
                vals = ", ".join(
                    f"{p}={'—' if v is None else format(v, ',.2f').rstrip('0').rstrip('.')}"
                    for p, v in rel.fetchall()
                )
            except Exception:
                vals = "(query failed)"
            print(f"    {col}")
            print(f"      {vals}")
    else:
        print("\n  no derived metrics depend on this key.")

    quarantined = [r for r in filing.quarantined if key in r.raw_label.lower()]
    if quarantined:
        print(f"\n  note: {len(quarantined)} quarantined row(s) mention this label.")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Turn a quarterly financial supplement PDF into clean structured data."
    )
    ap.add_argument("pdf", help="Path to the supplemental PDF")
    ap.add_argument("--db", default="data/filing.duckdb", help="DuckDB output path")
    ap.add_argument("--json", dest="json_path", default="data/filing.json")
    ap.add_argument("--company", default="Cloudflare, Inc.")
    ap.add_argument("--ticker", default="NET")
    ap.add_argument(
        "--no-llm",
        action="store_true",
        help="Use the deterministic alias table instead of the model",
    )
    ap.add_argument(
        "--compare",
        action="store_true",
        help="Run both normalizers and report disagreements",
    )
    ap.add_argument(
        "--html",
        nargs="?",
        const="data/report.html",
        default=None,
        metavar="PATH",
        help="Also write a standalone HTML report (default: data/report.html)",
    )
    ap.add_argument(
        "--trace",
        metavar="CANONICAL_KEY",
        default=None,
        help="Print the full provenance of one canonical key: source page, "
             "original label, the verbatim PDF line, and every derived metric "
             "built from it",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any accounting identity check fails",
    )
    args = ap.parse_args(argv)

    filing, rows = build_filing(
        args.pdf, use_llm=not args.no_llm, company=args.company, ticker=args.ticker
    )

    print(f"Extracted {len(rows)} raw rows -> {len(filing.line_items)} line items "
          f"across {len(filing.periods)} periods "
          f"({filing.periods[0]} .. {filing.periods[-1]})")
    if filing.quarantined:
        print(f"Quarantined {len(filing.quarantined)} rows (not dropped; "
              f"see the 'quarantined' table)")

    results = run_checks(filing)
    summary = summarize(results)
    print(f"\nAccounting identity checks: {summary['passed']}/{summary['total']} passed")
    for name, counts in sorted(summary["by_check"].items()):
        flag = "ok  " if counts["failed"] == 0 else "FAIL"
        print(f"  [{flag}] {name:34} {counts['passed']:>2} passed  "
              f"{counts['failed']:>2} failed")
    for r in results:
        if not r.passed:
            print(f"    ! {r.name} {r.period}: expected {r.expected:,.1f}, "
                  f"got {r.actual:,.1f} ({r.detail})")

    if args.compare:
        llm_items, _ = normalize(rows, use_llm=True)
        alias_items, _ = normalize(rows, use_llm=False)
        cmp = compare_normalizers(rows, llm_items, alias_items)
        print(f"\nNormalizer comparison: {cmp['agreements']}/{cmp['rows_both_mapped']} "
              f"agree on rows both could map")
        for d in cmp["disagreements"]:
            print(f"    p{d['page']} {d['label'][:52]!r}: llm={d['llm']} "
                  f"alias={d['alias']}")
        print(f"    model mapped {len(cmp['llm_only'])} rows the alias table could not")

    Path(args.json_path).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_path).write_text(filing.model_dump_json(indent=2))
    con = load(filing, args.db)
    print(f"\nWrote {args.json_path} and {args.db}")

    # Native DuckDB fetch, deliberately NOT .df(). The pandas helper is
    # convenient but drags in pandas and numpy as hard runtime dependencies
    # for the sake of turning eight rows into dicts. fetchall() also returns
    # None for SQL NULL, where the pandas path returns NaN and needs cleaning.
    funding = _records(con, "SELECT * FROM funding_mix")
    efficiency = _records(con, "SELECT * FROM growth_efficiency")

    if args.trace:
        trace_key(filing, con, args.trace)
        con.close()
        if args.strict and summary["failed"]:
            return 1
        return 0

    print("\nFunding mix (thousands USD):")
    con.sql("""
        SELECT period, delta_assets, delta_debt, delta_deferred_revenue,
               delta_apic, retained_earnings_change
        FROM funding_mix WHERE delta_assets IS NOT NULL
    """).show()

    print("Growth efficiency:")
    con.sql("""
        SELECT period, asset_turnover_ex_cash, revenue_growth_yoy_pct,
               incremental_op_margin_pct, current_op_margin_pct,
               gaap_gross_margin_pct
        FROM growth_efficiency
    """).show()
    con.close()

    if args.html:
        out = write_report(
            args.html,
            filing=filing,
            results=results,
            funding=funding,
            efficiency=efficiency,
            raw_row_count=len(rows),
        )
        print(f"Wrote {out}")

    if args.strict and summary["failed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
