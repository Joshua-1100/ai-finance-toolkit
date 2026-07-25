"""Passes 4 to 7 in isolation: group sums, digit-core identity, near amounts."""

from __future__ import annotations

import pytest

from recon.identity import memo_digit_core, normalize_memo
from recon.model import AmountQuality, DateQuality, IdentityQuality, Side
from recon.passes import (
    MAX_SUBSET_ROWS,
    NEAR_TOLERANCE_CENTS,
    digit_core,
    digit_core_dated,
    group_sum,
    near_amount,
)

from .helpers import make_file


# --- the digit core ------------------------------------------------------

@pytest.mark.parametrize("memo,expected", [
    ("Inv 000012345", "12345"),
    ("I12345", "12345"),
    ("12345", "12345"),
    ("INV12345", "12345"),
    ("#12345", "12345"),
    ("Inv 12345", "12345"),
    ("  inv-12345  ", "12345"),
    ("0000012345", "12345"),
])
def test_digit_core_sees_through_the_dressing(memo, expected):
    assert memo_digit_core(memo) == expected


@pytest.mark.parametrize("memo", [
    "",
    "Hsub",              # set 8 - a reversed name, no number at all
    "Inv",
    "Inv 12",            # two digits is too little to act on
    "Inv 007",           # strips to '7'
    "000",
    "0",
])
def test_digit_core_declines_weak_evidence(memo):
    assert memo_digit_core(memo) is None


def test_digit_core_keeps_internal_zeros():
    assert memo_digit_core("Inv 10203") == "10203"


def test_digit_core_concatenates_split_numbers():
    """A known limitation, pinned so it is a decision and not a surprise."""
    assert memo_digit_core("Inv 123 batch 45") == "12345"


def test_normalize_memo_folds_case_and_spacing():
    assert normalize_memo("  Inv   6060842 ") == "INV 6060842"


# --- pass 4: group sums --------------------------------------------------

def test_group_sum_claims_many_gl_to_one_bank():
    g = make_file(Side.GL, [(5, 1000, "Inv 700"), (5, 2500, "Inv 700")])
    b = make_file(Side.BANK, [(5, 3500, "Inv 700")])
    outcome = group_sum(g.rows, b.rows)
    assert len(outcome.proposals) == 1
    p = outcome.proposals[0]
    assert p.gl_ids == ["GL-0001", "GL-0002"]
    assert p.bank_ids == ["BK-0001"]
    assert p.amount is AmountQuality.SUM
    assert p.note == "2 GL rows sum to 35.00"


def test_group_sum_claims_one_gl_to_many_bank():
    g = make_file(Side.GL, [(5, 3500, "Inv 700")])
    b = make_file(Side.BANK, [(5, 1000, "Inv 700"), (5, 2500, "Inv 700")])
    outcome = group_sum(g.rows, b.rows)
    assert len(outcome.proposals) == 1
    p = outcome.proposals[0]
    assert p.gl_ids == ["GL-0001"]
    assert p.bank_ids == ["BK-0001", "BK-0002"]
    assert p.note == "2 bank rows sum to 35.00"


def test_group_sum_requires_the_sum_to_be_exact():
    g = make_file(Side.GL, [(5, 1000, "Inv 700"), (5, 2500, "Inv 700")])
    b = make_file(Side.BANK, [(5, 3501, "Inv 700")])
    assert group_sum(g.rows, b.rows).proposals == []


def test_group_sum_requires_a_shared_date():
    g = make_file(Side.GL, [(5, 1000, "Inv 700"), (6, 2500, "Inv 700")])
    b = make_file(Side.BANK, [(5, 3500, "Inv 700")])
    assert group_sum(g.rows, b.rows).proposals == []


def test_group_sum_requires_a_shared_memo():
    g = make_file(Side.GL, [(5, 1000, "Inv 700"), (5, 2500, "Inv 701")])
    b = make_file(Side.BANK, [(5, 3500, "Inv 700")])
    assert group_sum(g.rows, b.rows).proposals == []


def test_group_sum_finds_a_proper_subset():
    """Two of three rows settled; the third is a genuine open item."""
    g = make_file(Side.GL, [
        (5, 1000, "Inv 700"), (5, 2500, "Inv 700"), (5, 9999, "Inv 700"),
    ])
    b = make_file(Side.BANK, [(5, 3500, "Inv 700")])
    outcome = group_sum(g.rows, b.rows)
    assert len(outcome.proposals) == 1
    assert outcome.proposals[0].gl_ids == ["GL-0001", "GL-0002"]


def test_group_sum_flags_two_ways_to_reach_the_target():
    """10+40 and 20+30 both make 50. Which settled is not determined."""
    g = make_file(Side.GL, [
        (5, 1000, "Inv 700"), (5, 4000, "Inv 700"),
        (5, 2000, "Inv 700"), (5, 3000, "Inv 700"),
    ])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    outcome = group_sum(g.rows, b.rows)
    assert outcome.proposals == []
    assert len(outcome.ambiguities) == 1
    assert "different combinations" in outcome.ambiguities[0].reason


def test_group_sum_searches_when_signs_are_mixed():
    """The full-set shortcut is only valid for all-positive buckets.

    Here {30,20} and the full set both make 50, because the extra pair cancels.
    A negative amount in the bucket has to force the real search, or the
    shortcut would claim the full set and never notice the second answer.
    """
    g = make_file(Side.GL, [
        (5, 3000, "Inv 700"), (5, 2000, "Inv 700"),
        (5, 10000, "Inv 700"), (5, -10000, "Inv 700"),
    ])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    outcome = group_sum(g.rows, b.rows)
    assert outcome.proposals == []
    assert "different combinations" in outcome.ambiguities[0].reason


def test_group_sum_flags_multiple_rows_on_both_sides():
    g = make_file(Side.GL, [(5, 1000, "Inv 700"), (5, 2500, "Inv 700")])
    b = make_file(Side.BANK, [(5, 1500, "Inv 700"), (5, 2000, "Inv 700")])
    outcome = group_sum(g.rows, b.rows)
    assert outcome.proposals == []
    assert len(outcome.ambiguities) == 1
    assert "not determined" in outcome.ambiguities[0].reason


def test_group_sum_refuses_a_bucket_too_large_to_search():
    """A hanging reconciliation is not a reconciliation."""
    n = MAX_SUBSET_ROWS + 1
    # Powers of two, so no subset can coincidentally hit the target.
    g = make_file(Side.GL, [(5, 2 ** i, "Inv 700") for i in range(n)])
    b = make_file(Side.BANK, [(5, 999_999_99, "Inv 700")])
    outcome = group_sum(g.rows, b.rows)
    assert outcome.proposals == []
    assert len(outcome.ambiguities) == 1
    assert "search exhaustively" in outcome.ambiguities[0].reason


def test_group_sum_takes_the_full_set_without_searching():
    """All-positive amounts summing to the target admit no other answer."""
    n = MAX_SUBSET_ROWS + 5
    g = make_file(Side.GL, [(5, 100 + i, "Inv 700") for i in range(n)])
    total = sum(r.amount_cents for r in g.rows)
    b = make_file(Side.BANK, [(5, total, "Inv 700")])
    outcome = group_sum(g.rows, b.rows)
    assert len(outcome.proposals) == 1
    assert len(outcome.proposals[0].gl_ids) == n


def test_group_sum_ignores_a_single_row_each_side():
    """Not this pass's business - a 1:1 match belongs to an earlier one."""
    g = make_file(Side.GL, [(5, 3500, "Inv 700")])
    b = make_file(Side.BANK, [(5, 3500, "Inv 700")])
    assert group_sum(g.rows, b.rows).proposals == []


def test_group_sum_does_not_mutate_input():
    g = make_file(Side.GL, [(5, 1000, "Inv 700"), (5, 2500, "Inv 700")])
    b = make_file(Side.BANK, [(5, 3500, "Inv 700")])
    group_sum(g.rows, b.rows)
    assert all(r.match_id is None for r in g.rows + b.rows)


# --- passes 5 and 6: digit-core identity ---------------------------------

def test_digit_core_dated_claims_a_dressed_up_invoice():
    g = make_file(Side.GL, [(5, 5000, "Inv 000012345")])
    b = make_file(Side.BANK, [(5, 5000, "I12345")])
    p = digit_core_dated(g.rows, b.rows).proposals[0]
    assert p.identity is IdentityQuality.SIMILAR
    assert p.amount is AmountQuality.EXACT
    assert p.date is DateQuality.EXACT
    assert "same document number" in p.note


def test_digit_core_dated_requires_the_date():
    g = make_file(Side.GL, [(5, 5000, "Inv 000012345")])
    b = make_file(Side.BANK, [(6, 5000, "I12345")])
    assert digit_core_dated(g.rows, b.rows).proposals == []


def test_digit_core_dated_requires_the_amount():
    g = make_file(Side.GL, [(5, 5000, "Inv 000012345")])
    b = make_file(Side.BANK, [(5, 5001, "I12345")])
    assert digit_core_dated(g.rows, b.rows).proposals == []


def test_digit_core_matches_across_a_date_gap_and_grades_it():
    g = make_file(Side.GL, [(20, 5000, "Inv 000012345")])
    b = make_file(Side.BANK, [(2, 5000, "I12345")])
    p = digit_core(g.rows, b.rows).proposals[0]
    assert p.date is DateQuality.WIDE
    assert p.identity is IdentityQuality.SIMILAR
    assert "18 days after bank" in p.note  # GL day 20, bank day 2


def test_digit_core_skips_memos_with_no_number():
    """Set 8's reversed names must never be matched to each other."""
    g = make_file(Side.GL, [(5, 5000, "Hsub")])
    b = make_file(Side.BANK, [(5, 5000, "Nagaer")])
    assert digit_core(g.rows, b.rows).proposals == []
    assert digit_core_dated(g.rows, b.rows).proposals == []


def test_digit_core_refuses_when_the_core_does_not_single_out_a_pair():
    g = make_file(Side.GL, [(5, 5000, "Inv 12345"), (9, 5000, "I012345")])
    b = make_file(Side.BANK, [(5, 5000, "#12345")])
    outcome = digit_core(g.rows, b.rows)
    assert outcome.proposals == []
    assert len(outcome.ambiguities) == 1
    assert "does not single out a pair" in outcome.ambiguities[0].reason


def test_digit_core_does_not_mutate_input():
    g = make_file(Side.GL, [(5, 5000, "Inv 000012345")])
    b = make_file(Side.BANK, [(5, 5000, "I12345")])
    digit_core(g.rows, b.rows)
    assert all(r.match_id is None for r in g.rows + b.rows)


# --- pass 7: near amounts ------------------------------------------------

@pytest.mark.parametrize("difference", [1, 5, NEAR_TOLERANCE_CENTS])
def test_near_amount_claims_within_tolerance(difference):
    g = make_file(Side.GL, [(5, 5000 + difference, "Inv 700")])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    p = near_amount(g.rows, b.rows).proposals[0]
    assert p.amount is AmountQuality.NEAR
    assert p.date is DateQuality.EXACT
    assert p.identity is IdentityQuality.EXACT
    assert "over the bank amount" in p.note


def test_near_amount_reports_direction():
    g = make_file(Side.GL, [(5, 4995, "Inv 700")])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    assert near_amount(g.rows, b.rows).proposals[0].note == \
        "GL is 0.05 under the bank amount"


def test_near_amount_refuses_beyond_tolerance():
    g = make_file(Side.GL, [(5, 5000 + NEAR_TOLERANCE_CENTS + 1, "Inv 700")])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    assert near_amount(g.rows, b.rows).proposals == []


def test_near_amount_tolerance_is_configurable():
    g = make_file(Side.GL, [(5, 5050, "Inv 700")])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    assert near_amount(g.rows, b.rows, tolerance=9).proposals == []
    assert len(near_amount(g.rows, b.rows, tolerance=50).proposals) == 1


def test_near_amount_ignores_an_exact_match():
    """Zero difference is not this pass's business."""
    g = make_file(Side.GL, [(5, 5000, "Inv 700")])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    assert near_amount(g.rows, b.rows).proposals == []


def test_near_amount_requires_the_date():
    g = make_file(Side.GL, [(6, 5005, "Inv 700")])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    assert near_amount(g.rows, b.rows).proposals == []


def test_near_amount_refuses_when_several_rows_could_absorb_it():
    g = make_file(Side.GL, [(5, 5005, "Inv 700"), (5, 5003, "Inv 700")])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    outcome = near_amount(g.rows, b.rows)
    assert outcome.proposals == []
    assert len(outcome.ambiguities) == 1
    assert "not determined" in outcome.ambiguities[0].reason


def test_near_amount_does_not_mutate_input():
    g = make_file(Side.GL, [(5, 5005, "Inv 700")])
    b = make_file(Side.BANK, [(5, 5000, "Inv 700")])
    near_amount(g.rows, b.rows)
    assert all(r.match_id is None for r in g.rows + b.rows)
