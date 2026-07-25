"""The row and match model.

One row type serves both sides. The identity memo differs by name in the source
files - `line_memo` on the ledger, `messy_memo` on the statement - but it plays
the same role, so it lands in the same field.

`main_memo` is deliberately NOT an identity field. In the corpus it carries a
themed name that never appears on the bank side; it is context for the human
reviewing a match, not a key to match on.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum

from .money import format_cents


class Side(str, Enum):
    GL = "GL"
    BANK = "BANK"


class AmountQuality(str, Enum):
    """How well the money agrees."""

    EXACT = "Exact"    # equal to the cent, one row to one row
    SUM = "Sum"        # a group of rows sums exactly to the other side
    NEAR = "Near"      # within tolerance but not equal - a penny difference
    NONE = "None"


class DateQuality(str, Enum):
    """How well the dates agree."""

    EXACT = "Exact"    # same day
    CLOSE = "Close"    # a few days apart - normal settlement lag
    WIDE = "Wide"      # far enough apart to deserve a human look
    NONE = "None"


class IdentityQuality(str, Enum):
    """How well the memos agree."""

    EXACT = "Exact"      # identical strings
    SIMILAR = "Similar"  # same invoice wearing different clothes
    NONE = "None"


@dataclass
class LedgerRow:
    """One row from either file, with its identity and derived values.

    `row_id` is assigned at load in source order and never changes, so every
    downstream statement about this row traces back to a line in a file the
    user can open. `source_row` is the spreadsheet line number, header included,
    so it matches what Excel shows.
    """

    side: Side
    row_id: str
    source_row: int
    txn_date: date
    amount_cents: int
    memo: str
    main_memo: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    # Reserved for the matching passes. A match_id names a match *group*, so the
    # same value appears on every row that participates - which is how one
    # mechanism covers 1:1, many:1, 1:many and one-sided voids.
    match_id: str | None = None

    @property
    def amount(self) -> str:
        return format_cents(self.amount_cents)

    @property
    def matched(self) -> bool:
        return self.match_id is not None

    def __str__(self) -> str:
        return f"{self.row_id} {self.txn_date} {self.amount:>12} {self.memo}"


@dataclass
class LedgerFile:
    """A loaded side of the reconciliation."""

    side: Side
    path: str
    headers: list[str]
    rows: list[LedgerRow]
    warnings: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def total_cents(self) -> int:
        return sum(r.amount_cents for r in self.rows)

    @property
    def date_range(self) -> tuple[date, date] | None:
        if not self.rows:
            return None
        dates = [r.txn_date for r in self.rows]
        return min(dates), max(dates)

    def unmatched(self) -> list[LedgerRow]:
        return [r for r in self.rows if not r.matched]

    def copy_unmatched(self) -> LedgerFile:
        """A fresh copy with every match_id cleared.

        Reconciling mutates rows - that is the point of match_id living on the
        row. But it should not reach back and mutate the caller's data, so the
        engine works on a copy. That also makes reconcile() safe to run twice.
        """
        return LedgerFile(
            side=self.side,
            path=self.path,
            headers=list(self.headers),
            rows=[replace(r, raw=dict(r.raw), match_id=None) for r in self.rows],
            warnings=list(self.warnings),
        )


@dataclass
class Match:
    """One match group - the unit a reviewer accepts or rejects.

    Quality lives here rather than on the rows because it is a property of the
    group. Five ledger rows summing to one deposit share one verdict; storing
    that verdict five times invites the copies drifting apart.

    A group with rows on only one side is a legitimate outcome: a void pair that
    nets to zero, which is resolved without any counterparty.
    """

    match_id: str
    gl_ids: list[str]
    bank_ids: list[str]
    amount: AmountQuality
    date: DateQuality
    identity: IdentityQuality
    rule: str = ""            # which pass claimed it, for auditability
    note: str = ""            # why, when the verdict needs a sentence

    @property
    def shape(self) -> str:
        """'1:1', '3:1', '1:5', '2:0' - readable at a glance in Excel."""
        return f"{len(self.gl_ids)}:{len(self.bank_ids)}"

    @property
    def one_sided(self) -> bool:
        return not self.gl_ids or not self.bank_ids
