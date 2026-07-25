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

import itertools
from collections import defaultdict
from typing import Callable, Sequence

from .engine import Ambiguity, MatchPass, PassResult, Proposal
from .identity import memo_digit_core, normalize_memo
from .model import AmountQuality, DateQuality, IdentityQuality, LedgerRow
from .money import format_cents


def _index(rows: Sequence[LedgerRow], key) -> dict[tuple, list[LedgerRow]]:
    """Bucket rows by a key function, preserving row order within a bucket.

    A key function returning None excludes that row - which is how the fuzzy
    passes skip memos with no usable document number.
    """
    buckets: dict[tuple, list[LedgerRow]] = defaultdict(list)
    for row in rows:
        k = key(row)
        if k is not None:
            buckets[k].append(row)
    return buckets


# The grade callback returns the three quality axes plus a note, given the
# matched pair. Each pass decides what its own evidence is worth.
GradeFn = Callable[
    [LedgerRow, LedgerRow],
    "tuple[AmountQuality, DateQuality, IdentityQuality, str]",
]


def _claim_unique_pairs(
    gl_rows: Sequence[LedgerRow],
    bank_rows: Sequence[LedgerRow],
    key,
    pass_name: str,
    describe: Callable[[tuple], str],
    grade: GradeFn,
) -> PassResult:
    """Index both sides, claim where exactly one row a side shares a key.

    The shape every one-to-one pass wants: agree on the key, refuse where the
    key does not single out a pair.
    """
    gl_index = _index(gl_rows, key)
    bank_index = _index(bank_rows, key)

    result = PassResult()
    for k in sorted(gl_index.keys() & bank_index.keys()):
        gl_bucket, bank_bucket = gl_index[k], bank_index[k]

        if len(gl_bucket) > 1 or len(bank_bucket) > 1:
            result.ambiguities.append(Ambiguity(
                pass_name=pass_name,
                key=describe(k),
                gl_ids=[r.row_id for r in gl_bucket],
                bank_ids=[r.row_id for r in bank_bucket],
                reason=(
                    f"{len(gl_bucket)} GL and {len(bank_bucket)} bank rows share "
                    "this key - it does not single out a pair, so not claimed"
                ),
            ))
            continue

        gl_row, bank_row = gl_bucket[0], bank_bucket[0]
        amount, date_q, identity, note = grade(gl_row, bank_row)
        result.proposals.append(Proposal(
            gl_ids=[gl_row.row_id],
            bank_ids=[bank_row.row_id],
            amount=amount,
            date=date_q,
            identity=identity,
            note=note,
        ))
    return result


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


# --- pass 4: a group on one side summing to one row on the other ---------

# 2**12 is four thousand subsets, which is instant. Beyond that the search is
# refused rather than allowed to crawl: a bucket of thirty rows is 10**9
# combinations, and a reconciliation that hangs is not a reconciliation.
MAX_SUBSET_ROWS = 12


def _subsets_summing_to(
    rows: Sequence[LedgerRow], target: int,
) -> list[tuple[LedgerRow, ...]] | None:
    """Every subset of two or more rows summing exactly to target.

    Returns None when the bucket is too large to search exhaustively.

    Single rows are excluded because a one-to-one match at this amount would
    already have been claimed by an earlier pass.
    """
    if sum(r.amount_cents for r in rows) == target and all(
        r.amount_cents > 0 for r in rows
    ):
        # All amounts positive means every proper subset sums to strictly less
        # than the whole, so the full set is the only answer and there is no
        # search to do. Mixed signs break that guarantee and fall through.
        return [tuple(rows)]

    if len(rows) > MAX_SUBSET_ROWS:
        return None

    found: list[tuple[LedgerRow, ...]] = []
    for size in range(2, len(rows) + 1):
        for combo in itertools.combinations(rows, size):
            if sum(r.amount_cents for r in combo) == target:
                found.append(combo)
    return found


def group_sum(
    gl_rows: Sequence[LedgerRow], bank_rows: Sequence[LedgerRow],
) -> PassResult:
    """One deposit covering several ledger lines, or one entry split across
    several bank items.

    Bucketed by date and memo first, which is what makes this tractable.
    Unconstrained subset-sum over ten thousand rows is not a computation anyone
    finishes; over the handful of rows sharing a date and a reference it is
    immediate.

    Only the clean shapes are claimed - one row on one side against two or more
    on the other. A bucket with several rows on both sides has no determined
    answer, and neither does one where two different subsets reach the target,
    so both are flagged.
    """
    def key(row: LedgerRow) -> tuple:
        return (row.txn_date, normalize_memo(row.memo))

    gl_index = _index(gl_rows, key)
    bank_index = _index(bank_rows, key)

    result = PassResult()
    for k in sorted(gl_index.keys() & bank_index.keys()):
        gl_bucket, bank_bucket = gl_index[k], bank_index[k]
        date, memo = k
        bucket_key = f"{date} / {memo}"

        if len(bank_bucket) == 1 and len(gl_bucket) >= 2:
            many, one, many_is_gl = gl_bucket, bank_bucket[0], True
        elif len(gl_bucket) == 1 and len(bank_bucket) >= 2:
            many, one, many_is_gl = bank_bucket, gl_bucket[0], False
        elif len(gl_bucket) >= 2 and len(bank_bucket) >= 2:
            result.ambiguities.append(Ambiguity(
                pass_name="group_sum",
                key=bucket_key,
                gl_ids=[r.row_id for r in gl_bucket],
                bank_ids=[r.row_id for r in bank_bucket],
                reason=(
                    f"{len(gl_bucket)} GL and {len(bank_bucket)} bank rows share "
                    "a date and memo - which rows group with which is not "
                    "determined, so not claimed"
                ),
            ))
            continue
        else:
            continue

        subsets = _subsets_summing_to(many, one.amount_cents)
        many_ids = [r.row_id for r in many]

        if subsets is None:
            result.ambiguities.append(Ambiguity(
                pass_name="group_sum",
                key=bucket_key,
                gl_ids=many_ids if many_is_gl else [one.row_id],
                bank_ids=[one.row_id] if many_is_gl else many_ids,
                reason=(
                    f"{len(many)} rows share a date and memo, more than the "
                    f"{MAX_SUBSET_ROWS} this pass will search exhaustively - "
                    "not claimed"
                ),
            ))
            continue

        if not subsets:
            continue

        if len(subsets) > 1:
            result.ambiguities.append(Ambiguity(
                pass_name="group_sum",
                key=bucket_key,
                gl_ids=many_ids if many_is_gl else [one.row_id],
                bank_ids=[one.row_id] if many_is_gl else many_ids,
                reason=(
                    f"{len(subsets)} different combinations of these rows sum to "
                    f"{one.amount} - which one settled is not determined, so not "
                    "claimed"
                ),
            ))
            continue

        group = list(subsets[0])
        side = "GL" if many_is_gl else "bank"
        result.proposals.append(Proposal(
            gl_ids=[r.row_id for r in group] if many_is_gl else [one.row_id],
            bank_ids=[one.row_id] if many_is_gl else [r.row_id for r in group],
            amount=AmountQuality.SUM,
            date=DateQuality.EXACT,
            identity=IdentityQuality.EXACT,
            note=f"{len(group)} {side} rows sum to {one.amount}",
        ))
    return result


# --- passes 5 and 6: the same document, differently written --------------

def digit_core_dated(
    gl_rows: Sequence[LedgerRow], bank_rows: Sequence[LedgerRow],
) -> PassResult:
    """Same date, same amount, and the same document number inside the memo.

    'Inv 000012345' against 'I12345'. The amount and date agreeing exactly does
    most of the work here; the digit core is what turns a coincidence into an
    identification.
    """
    def key(row: LedgerRow) -> tuple | None:
        core = memo_digit_core(row.memo)
        return None if core is None else (row.txn_date, row.amount_cents, core)

    return _claim_unique_pairs(
        gl_rows, bank_rows, key, pass_name="digit_core_dated",
        describe=lambda k: f"{k[0]} / {k[1]} / core {k[2]}",
        grade=lambda g, b: (
            AmountQuality.EXACT, DateQuality.EXACT, IdentityQuality.SIMILAR,
            f"same document number, memos differ: {g.memo!r} vs {b.memo!r}",
        ),
    )


def digit_core(
    gl_rows: Sequence[LedgerRow],
    bank_rows: Sequence[LedgerRow],
    close_days: int = CLOSE_DAYS,
) -> PassResult:
    """Same amount and document number, date free and graded.

    The weakest identity evidence the ladder acts on, so it runs late and only
    where the amount still agrees to the cent.
    """
    def key(row: LedgerRow) -> tuple | None:
        core = memo_digit_core(row.memo)
        return None if core is None else (row.amount_cents, core)

    def grade(g: LedgerRow, b: LedgerRow):
        gap = (g.txn_date - b.txn_date).days
        direction = "after" if gap > 0 else "before"
        return (
            AmountQuality.EXACT,
            date_quality(gap, close_days),
            IdentityQuality.SIMILAR,
            f"same document number, memos differ: {g.memo!r} vs {b.memo!r}; "
            f"GL {abs(gap)} day{'' if abs(gap) == 1 else 's'} {direction} bank",
        )

    return _claim_unique_pairs(
        gl_rows, bank_rows, key, pass_name="digit_core",
        describe=lambda k: f"{k[0]} / core {k[1]}",
        grade=grade,
    )


# --- pass 7: the amount is off by a rounding artifact --------------------

# Deliberately tiny. This pass exists for pennies lost to rounding or a
# conversion, not for genuine differences - an amount off by more than this is
# a discrepancy a human should see, not one a tool should absorb.
NEAR_TOLERANCE_CENTS = 9


def near_amount(
    gl_rows: Sequence[LedgerRow],
    bank_rows: Sequence[LedgerRow],
    tolerance: int = NEAR_TOLERANCE_CENTS,
) -> PassResult:
    """Same date, same memo, amount off by no more than a few cents.

    The last and weakest pass. It requires the date and memo to agree exactly,
    because once the amount is allowed to move, everything else has to hold
    still. Whatever difference it accepts is carried into the proof as drift, so
    the reconciliation still foots to the cent.
    """
    def key(row: LedgerRow) -> tuple:
        return (row.txn_date, normalize_memo(row.memo))

    gl_index = _index(gl_rows, key)
    bank_index = _index(bank_rows, key)

    result = PassResult()
    for k in sorted(gl_index.keys() & bank_index.keys()):
        gl_bucket, bank_bucket = gl_index[k], bank_index[k]
        date, memo = k

        candidates = [
            (g, b)
            for g in gl_bucket
            for b in bank_bucket
            if 0 < abs(g.amount_cents - b.amount_cents) <= tolerance
        ]
        if not candidates:
            continue

        if len(candidates) > 1 or len(gl_bucket) > 1 or len(bank_bucket) > 1:
            result.ambiguities.append(Ambiguity(
                pass_name="near_amount",
                key=f"{date} / {memo}",
                gl_ids=[r.row_id for r in gl_bucket],
                bank_ids=[r.row_id for r in bank_bucket],
                reason=(
                    f"{len(candidates)} pairing(s) within {tolerance} cents among "
                    f"{len(gl_bucket)} GL and {len(bank_bucket)} bank rows - which "
                    "row absorbed the difference is not determined, so not claimed"
                ),
            ))
            continue

        gl_row, bank_row = candidates[0]
        difference = gl_row.amount_cents - bank_row.amount_cents
        result.proposals.append(Proposal(
            gl_ids=[gl_row.row_id],
            bank_ids=[bank_row.row_id],
            amount=AmountQuality.NEAR,
            date=DateQuality.EXACT,
            identity=IdentityQuality.EXACT,
            note=f"GL is {format_cents(abs(difference))} "
                 f"{'over' if difference > 0 else 'under'} the bank amount",
        ))
    return result


# The order is the design. Each pass sees only what the stronger ones left, so
# moving an entry up the list gives it first claim on rows it has weaker
# evidence for.
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
    MatchPass(
        name="group_sum",
        description="A group on one side summing exactly to one row on the other",
        run=group_sum,
    ),
    MatchPass(
        name="digit_core_dated",
        description="Same date and amount, same document number in the memo",
        run=digit_core_dated,
    ),
    MatchPass(
        name="digit_core",
        description="Same amount and document number, date graded",
        run=digit_core,
    ),
    MatchPass(
        name="near_amount",
        description="Same date and memo, amount within a few cents",
        run=near_amount,
    ),
]
