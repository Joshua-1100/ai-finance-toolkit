"""Console reporting for the load stage.

The one number worth printing before any matching happens is the difference
between the two files. That difference is the whole job: every unmatched item
the reconciliation ends up reporting has to add back to exactly this figure, or
the reconciliation is wrong.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from .engine import Result
from .explain import Explanation
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

    return "\n".join(out)


def match_report(result: Result) -> str:
    """What the passes claimed, and whether the difference still foots."""
    gl_n, bank_n = len(result.gl.rows), len(result.bank.rows)
    out: list[str] = ["", RULE, "MATCHING", RULE]

    for name, count in result.pass_counts:
        out.append(f"  {name:<20} {count:>4} match{'' if count == 1 else 'es'}")

    out.append("")
    out.append(f"  {len(result.matches)} match groups covering "
               f"{result.matched_gl_count} GL and {result.matched_bank_count} bank rows")

    shapes = Counter(m.shape for m in result.matches)
    if shapes:
        pretty = ", ".join(f"{n} x {shape}" for shape, n in sorted(shapes.items()))
        out.append(f"  shapes: {pretty}")

    quality = Counter((m.amount.value, m.date.value, m.identity.value)
                      for m in result.matches)
    if quality:
        out.append("")
        out.append(f"  {'amount':<8} {'date':<8} {'identity':<9} {'groups':>6}")
        for (amount, date_q, identity), n in sorted(quality.items()):
            out.append(f"  {amount:<8} {date_q:<8} {identity:<9} {n:>6}")

    if result.ambiguities:
        out += ["", RULE, f"NOT CLAIMED - AMBIGUOUS ({len(result.ambiguities)})", RULE]
        out.append("  Candidates the passes declined rather than guess between.")
        for amb in result.ambiguities[:10]:
            out.append(f"  [{amb.pass_name}] {amb.key}")
            out.append(f"      GL {', '.join(amb.gl_ids) or '-'}"
                       f"  vs  BANK {', '.join(amb.bank_ids) or '-'}")
            out.append(f"      {amb.reason}")
        if len(result.ambiguities) > 10:
            out.append(f"  ... and {len(result.ambiguities) - 10} more")

    unmatched_gl_cents = sum(r.amount_cents for r in result.unmatched_gl)
    unmatched_bank_cents = sum(r.amount_cents for r in result.unmatched_bank)

    out += ["", RULE, "STILL OPEN", RULE]
    out.append(f"  GL    {len(result.unmatched_gl):>4} of {gl_n} rows"
               f"   {format_cents_grouped(unmatched_gl_cents):>14}")
    out.append(f"  Bank  {len(result.unmatched_bank):>4} of {bank_n} rows"
               f"   {format_cents_grouped(unmatched_bank_cents):>14}")

    out += ["", RULE, "PROOF", RULE]
    difference = result.gl.total_cents - result.bank.total_cents
    out.append(f"  unmatched GL less unmatched bank  "
               f"{format_cents_grouped(unmatched_gl_cents - unmatched_bank_cents):>14}")
    out.append(f"  drift accepted inside matches     "
               f"{format_cents_grouped(result.drift_cents):>14}")
    out.append(f"  {'':<33}{'':->14}")
    out.append(f"  accounted for                     "
               f"{format_cents_grouped(unmatched_gl_cents - unmatched_bank_cents + result.drift_cents):>14}")
    out.append(f"  GL total less bank total          "
               f"{format_cents_grouped(difference):>14}")

    foots = (unmatched_gl_cents - unmatched_bank_cents + result.drift_cents) == difference
    out.append("")
    out.append(f"  {'FOOTS' if foots else 'DOES NOT FOOT'} - the reconciliation is "
               f"{'complete' if foots else 'INCOMPLETE'}.")
    out.append("")
    return "\n".join(out)


def explanation_report(explanations: Sequence[Explanation]) -> str:
    """The model's read on each declined candidate. Advisory, never decisive."""
    if not explanations:
        return ""

    worked = [e for e in explanations if not e.failed]
    out: list[str] = ["", RULE, f"EXPLAINED ({len(worked)} of {len(explanations)})", RULE]
    out.append("  A model's read on what each declined candidate probably is.")
    out.append("  Advisory only - no explanation changed a match.")
    out.append("")

    for e in explanations:
        gl = ", ".join(e.gl_ids) or "-"
        bank = ", ".join(e.bank_ids) or "-"
        out.append(f"  [{e.pass_name}] GL {gl}  vs  BANK {bank}")
        if e.failed:
            out.append(f"      {e.summary}")
        else:
            out.append(f"      cause: {e.cause_label}   check: {e.check_label}")
            out.append(f"      {e.summary}")
        out.append("")

    if worked:
        out.append(f"  Explained by {worked[0].model}.")
        out.append("")
    return "\n".join(out)
