"""The matching passes, strongest evidence first.

Every pass follows the same shape: build an index over the rows still available
on each side, then claim only where the index forces a single answer. Indexing
rather than nesting loops is what keeps this linear - it matters little at 205
rows a side and a great deal at ten thousand.

The ladder is deliberately ordered. Once a pass claims a row it leaves the pool,
so a weaker pass running early could take a row a stronger pass needed. Ordering
by evidence strength keeps that from happening.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from .engine import Ambiguity, MatchPass, PassResult, Proposal
from .identity import normalize_memo
from .model import AmountQuality, DateQuality, IdentityQuality, LedgerRow


def _index(rows: Sequence[LedgerRow], key) -> dict[tuple, list[LedgerRow]]:
    """Bucket rows by a key function, preserving row order within a bucket."""
    buckets: dict[tuple, list[LedgerRow]] = defaultdict(list)
    for row in rows:
        buckets[key(row)].append(row)
    return buckets


# --- pass 1: exact on all three axes -------------------------------------

def exact_triple(
    gl_rows: Sequence[LedgerRow], bank_rows: Sequence[LedgerRow],
) -> PassResult:
    """Same day, same cents, same memo. The matches nobody would argue with.

    Case and internal spacing are folded before comparing, since those are
    artifacts of the exporting system rather than differences in the data.

    Where a key holds more than one row on either side the pass declines: two
    ledger rows identical in date, amount and memo cannot be told apart, and
    picking one would be a guess dressed up as an answer.
    """
    def key(row: LedgerRow) -> tuple:
        return (row.txn_date, row.amount_cents, normalize_memo(row.memo))

    gl_index = _index(gl_rows, key)
    bank_index = _index(bank_rows, key)

    result = PassResult()
    # Sorted for determinism: the set of shared keys is order-independent, but
    # the order we walk it decides the order proposals are generated.
    for k in sorted(gl_index.keys() & bank_index.keys()):
        gl_bucket, bank_bucket = gl_index[k], bank_index[k]
        if len(gl_bucket) > 1 or len(bank_bucket) > 1:
            date, cents, memo = k
            result.ambiguities.append(Ambiguity(
                pass_name="exact_triple",
                key=f"{date} / {cents} / {memo}",
                gl_ids=[r.row_id for r in gl_bucket],
                bank_ids=[r.row_id for r in bank_bucket],
                reason=(
                    f"{len(gl_bucket)} GL and {len(bank_bucket)} bank rows share "
                    "date, amount and memo - indistinguishable, so not claimed"
                ),
            ))
            continue

        result.proposals.append(Proposal(
            gl_ids=[gl_bucket[0].row_id],
            bank_ids=[bank_bucket[0].row_id],
            amount=AmountQuality.EXACT,
            date=DateQuality.EXACT,
            identity=IdentityQuality.EXACT,
        ))
    return result


# --- pass 2: void pairs within one file ----------------------------------

def _find_voids(
    rows: Sequence[LedgerRow], side_name: str, result: PassResult,
) -> None:
    """Pair equal-and-opposite rows that share a date and memo, within one file."""
    buckets = _index(rows, lambda r: (r.txn_date, normalize_memo(r.memo)))

    for date, memo in sorted(buckets.keys()):
        bucket = buckets[(date, memo)]
        if len(bucket) < 2:
            continue

        by_magnitude: dict[int, dict[str, list[LedgerRow]]] = defaultdict(
            lambda: {"pos": [], "neg": []}
        )
        for row in bucket:
            # A zero-amount row cannot be a leg of a void, and claiming one on
            # its own would be presumptuous. It stays open for a human to close.
            if row.amount_cents == 0:
                continue
            slot = by_magnitude[abs(row.amount_cents)]
            slot["pos" if row.amount_cents > 0 else "neg"].append(row)

        for magnitude in sorted(by_magnitude):
            positive = by_magnitude[magnitude]["pos"]
            negative = by_magnitude[magnitude]["neg"]
            if not positive or not negative:
                continue

            if len(positive) != 1 or len(negative) != 1:
                result.ambiguities.append(Ambiguity(
                    pass_name="void_pairs",
                    key=f"{side_name} / {date} / {memo} / +-{magnitude}",
                    gl_ids=[r.row_id for r in positive + negative]
                    if side_name == "GL" else [],
                    bank_ids=[r.row_id for r in positive + negative]
                    if side_name == "BANK" else [],
                    reason=(
                        f"{len(positive)} positive and {len(negative)} negative rows "
                        f"of the same magnitude share a date and memo - which "
                        f"cancels which is not determined, so not claimed"
                    ),
                ))
                continue

            ids = [positive[0].row_id, negative[0].row_id]
            result.proposals.append(Proposal(
                gl_ids=ids if side_name == "GL" else [],
                bank_ids=ids if side_name == "BANK" else [],
                amount=AmountQuality.EXACT,
                date=DateQuality.EXACT,
                identity=IdentityQuality.EXACT,
                note=f"void pair within {side_name}, nets to zero",
            ))


def void_pairs(
    gl_rows: Sequence[LedgerRow], bank_rows: Sequence[LedgerRow],
) -> PassResult:
    """An entry and its reversal, resolved without any counterparty.

    A void has nothing to match on the other side - the signal is two rows in
    the *same* file, same date, same memo, equal and opposite. Reporting them as
    two unmatched items would be technically true and practically useless.

    Deliberately narrow: only a single positive against a single negative of the
    same magnitude. A bucket holding two of either is flagged, not paired, since
    which reverses which is not determined. Nor does this chase combinations
    that net to zero in aggregate - a rule a reviewer cannot follow is worse
    than one that leaves a few items open.

    Runs after exact_triple on purpose. If the positive leg genuinely cleared
    the bank, that is a real match and the reversal is a real open item; letting
    the stronger cross-file evidence go first gets that case right.
    """
    result = PassResult()
    _find_voids(gl_rows, "GL", result)
    _find_voids(bank_rows, "BANK", result)
    return result


# --- pass 3: amount and memo agree, date is free -------------------------

CLOSE_DAYS = 3


def date_quality(gap_days: int, close_days: int = CLOSE_DAYS) -> DateQuality:
    """Grade a date gap. The sign does not matter, the size does."""
    gap = abs(gap_days)
    if gap == 0:
        return DateQuality.EXACT
    if gap <= close_days:
        return DateQuality.CLOSE
    return DateQuality.WIDE


def amount_memo(
    gl_rows: Sequence[LedgerRow],
    bank_rows: Sequence[LedgerRow],
    close_days: int = CLOSE_DAYS,
) -> PassResult:
    """Same amount, same memo, any date - the settlement-lag matches.

    Amount and memo agreeing exactly is strong evidence on its own, so the date
    is graded rather than required: Close for a few days, Wide beyond that. A
    Wide match is still a match, but it is flagged for a look, because on a
    period-end reconciliation a large gap can be a cutoff error rather than
    slow settlement.

    No upper bound on the gap. Refusing a match whose amount and memo both
    agree would leave a reviewer with two items that obviously belong together
    and no explanation for why the tool disagreed.
    """
    def key(row: LedgerRow) -> tuple:
        return (row.amount_cents, normalize_memo(row.memo))

    gl_index = _index(gl_rows, key)
    bank_index = _index(bank_rows, key)

    result = PassResult()
    for k in sorted(gl_index.keys() & bank_index.keys()):
        gl_bucket, bank_bucket = gl_index[k], bank_index[k]
        cents, memo = k

        if len(gl_bucket) > 1 or len(bank_bucket) > 1:
            result.ambiguities.append(Ambiguity(
                pass_name="amount_memo",
                key=f"{cents} / {memo}",
                gl_ids=[r.row_id for r in gl_bucket],
                bank_ids=[r.row_id for r in bank_bucket],
                reason=(
                    f"{len(gl_bucket)} GL and {len(bank_bucket)} bank rows share "
                    "an amount and memo - the date alone would decide it, which "
                    "is a guess, so not claimed"
                ),
            ))
            continue

        gl_row, bank_row = gl_bucket[0], bank_bucket[0]
        gap = (gl_row.txn_date - bank_row.txn_date).days
        quality = date_quality(gap, close_days)
        direction = "after" if gap > 0 else "before"
        result.proposals.append(Proposal(
            gl_ids=[gl_row.row_id],
            bank_ids=[bank_row.row_id],
            amount=AmountQuality.EXACT,
            date=quality,
            identity=IdentityQuality.EXACT,
            note=f"GL {abs(gap)} day{'' if abs(gap) == 1 else 's'} {direction} bank",
        ))
    return result


DEFAULT_PASSES: list[MatchPass] = [
    MatchPass(
        name="exact_triple",
        description="Same date, same amount, same memo",
        run=exact_triple,
    ),
    MatchPass(
        name="void_pairs",
        description="Equal and opposite within one file, same date and memo",
        run=void_pairs,
    ),
    MatchPass(
        name="amount_memo",
        description="Same amount and memo, date graded by the gap",
        run=amount_memo,
    ),
]
