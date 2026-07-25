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


DEFAULT_PASSES: list[MatchPass] = [
    MatchPass(
        name="exact_triple",
        description="Same date, same amount, same memo",
        run=exact_triple,
    ),
]
