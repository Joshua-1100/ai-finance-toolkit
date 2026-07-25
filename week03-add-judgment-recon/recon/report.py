"""Console reporting for the load stage.

The one number worth printing before any matching happens is the difference
between the two files. That difference is the whole job: every unmatched item
the reconciliation ends up reporting has to add back to exactly this figure, or
the reconciliation is wrong.
"""

from __future__ import annotations

from collections import Counter

from .model import LedgerFile
from .money import format_cents_grouped

RULE = "-" * 68


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def describe_file(f: LedgerFile) -> list[str]:
    lines = [f"{f.side.value:<5} {f.path}"]
    span = f.date_range
    negatives = sum(1 for r in f.rows if r.amount_cents < 0)
    blank_memos = sum(1 for r in f.rows if not r.memo)

    lines.append(f"      rows          {len(f)}  ({f.rows[0].row_id} .. {f.rows[-1].row_id})")
    if span:
        lines.append(f"      dates         {span[0]} to {span[1]}")
    lines.append(f"      total         {format_cents_grouped(f.total_cents):>16}")
    if negatives:
        lines.append(f"      negative      {_plural(negatives, 'row')}")
    if blank_memos:
        lines.append(f"      blank memos   {_plural(blank_memos, 'row')}")

    # Repeated amounts are where naive matching goes wrong: two ledger rows at
    # the same amount can each claim the same deposit. Surfaced now because it
    # sets the difficulty of the matching passes to come.
    repeats = Counter(r.amount_cents for r in f.rows)
    ambiguous = sum(c for c in repeats.values() if c > 1)
    if ambiguous:
        lines.append(
            f"      repeated amts {ambiguous} rows share an amount with another row"
        )
    return lines


def load_report(gl: LedgerFile, bank: LedgerFile) -> str:
    out: list[str] = ["", RULE, "LOADED", RULE]
    out += describe_file(gl)
    out.append("")
    out += describe_file(bank)

    difference = gl.total_cents - bank.total_cents
    out += ["", RULE, "CONTROL TOTAL", RULE]
    out.append(f"  GL total                {format_cents_grouped(gl.total_cents):>16}")
    out.append(f"  Bank total              {format_cents_grouped(bank.total_cents):>16}")
    out.append(f"  Difference to explain   {format_cents_grouped(difference):>16}")
    out.append("")
    out.append("  Every unmatched item the reconciliation reports must add back")
    out.append("  to this difference. That is the proof the recon is complete.")

    warnings = [(gl.side.value, w) for w in gl.warnings]
    warnings += [(bank.side.value, w) for w in bank.warnings]
    if warnings:
        out += ["", RULE, f"WARNINGS ({len(warnings)})", RULE]
        for side, warning in warnings[:20]:
            out.append(f"  {side}: {warning}")
        if len(warnings) > 20:
            out.append(f"  ... and {len(warnings) - 20} more")

    out += ["", RULE, "NEXT", RULE]
    out.append(f"  {len(gl)} GL rows and {len(bank)} bank rows are enumerated and")
    out.append("  carry an empty match_id, ready for the matching passes.")
    out.append("")
    return "\n".join(out)
