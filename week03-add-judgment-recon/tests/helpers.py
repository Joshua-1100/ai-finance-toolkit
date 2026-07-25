"""Row and file builders for tests that need a specific arrangement rather than
the whole corpus."""

from __future__ import annotations

from datetime import date
from typing import Iterable, Sequence

from recon.model import LedgerFile, LedgerRow, Side


def make_row(side: Side, n: int, day: int, cents: int, memo: str) -> LedgerRow:
    """One row, dated within May 2026 to match the corpus range."""
    prefix = "GL" if side is Side.GL else "BK"
    return LedgerRow(
        side=side,
        row_id=f"{prefix}-{n:04d}",
        source_row=n + 1,
        txn_date=date(2026, 5, day),
        amount_cents=cents,
        memo=memo,
    )


def make_file(
    side: Side, specs: Iterable[tuple[int, int, str]],
) -> LedgerFile:
    """A LedgerFile from (day, cents, memo) tuples, enumerated from 1."""
    rows = [make_row(side, i, d, c, m) for i, (d, c, m) in enumerate(specs, 1)]
    return LedgerFile(side=side, path=f"<{side.value}>", headers=[], rows=rows)
