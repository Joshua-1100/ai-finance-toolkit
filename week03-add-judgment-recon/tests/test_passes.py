"""Passes 2 and 3, plus the behaviour of the ladder as a whole."""

from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from recon.engine import reconcile
from recon.model import AmountQuality, DateQuality, IdentityQuality, Side
from recon.passes import (
    amount_memo,
    date_quality,
    exact_triple,
    void_pairs,
)

from .helpers import make_file


# --- pass 2: voids -------------------------------------------------------

def test_void_finds_a_gl_pair():
    g = make_file(Side.GL, [(5, 10000, "Inv 7"), (5, -10000, "Inv 7")])
    b = make_file(Side.BANK, [])
    outcome = void_pairs(g.rows, b.rows)
    assert len(outcome.proposals) == 1
    p = outcome.proposals[0]
    assert p.gl_ids == ["GL-0001", "GL-0002"]
    assert p.bank_ids == []
    assert "nets to zero" in p.note


def test_void_finds_a_bank_pair():
    g = make_file(Side.GL, [])
    b = make_file(Side.BANK, [(5, 30000, "Inv 9"), (5, -30000, "Inv 9")])
    outcome = void_pairs(g.rows, b.rows)
    assert len(outcome.proposals) == 1
    assert outcome.proposals[0].bank_ids == ["BK-0001", "BK-0002"]
    assert outcome.proposals[0].gl_ids == []


def test_void_requires_the_same_date():
    g = make_file(Side.GL, [(5, 10000, "Inv 7"), (6, -10000, "Inv 7")])
    assert void_pairs(g.rows, []).proposals == []


def test_void_requires_the_same_memo():
    g = make_file(Side.GL, [(5, 10000, "Inv 7"), (5, -10000, "Inv 8")])
    assert void_pairs(g.rows, []).proposals == []


def test_void_requires_equal_magnitude():
    g = make_file(Side.GL, [(5, 10000, "Inv 7"), (5, -9900, "Inv 7")])
    assert void_pairs(g.rows, []).proposals == []


def test_void_needs_both_a_positive_and_a_negative():
    g = make_file(Side.GL, [(5, 10000, "Inv 7"), (5, 10000, "Inv 7")])
    outcome = void_pairs(g.rows, [])
    assert outcome.proposals == []
    assert outcome.ambiguities == []  # same sign is not a void at all


def test_void_refuses_when_pairing_is_undetermined():
    """Two positives and one negative: which reverses which is not decidable."""
    g = make_file(Side.GL, [
        (5, 10000, "Inv 7"), (5, 10000, "Inv 7"), (5, -10000, "Inv 7"),
    ])
    outcome = void_pairs(g.rows, [])
    assert outcome.proposals == []
    assert len(outcome.ambiguities) == 1
    assert "not determined" in outcome.ambiguities[0].reason
    assert outcome.ambiguities[0].gl_ids == ["GL-0001", "GL-0002", "GL-0003"]


def test_void_ignores_zero_amount_rows():
    g = make_file(Side.GL, [(5, 0, "Inv 7"), (5, 0, "Inv 7")])
    assert void_pairs(g.rows, []).proposals == []


def test_void_handles_two_distinct_magnitudes_in_one_bucket():
    g = make_file(Side.GL, [
        (5, 10000, "Inv 7"), (5, -10000, "Inv 7"),
        (5, 25000, "Inv 7"), (5, -25000, "Inv 7"),
    ])
    outcome = void_pairs(g.rows, [])
    assert len(outcome.proposals) == 2
    assert all(len(p.gl_ids) == 2 for p in outcome.proposals)


def test_void_does_not_mutate_input():
    g = make_file(Side.GL, [(5, 10000, "Inv 7"), (5, -10000, "Inv 7")])
    void_pairs(g.rows, [])
    assert all(r.match_id is None for r in g.rows)


# --- pass 3: amount and memo, date free ----------------------------------

@pytest.mark.parametrize("gap,expected", [
    (0, DateQuality.EXACT),
    (1, DateQuality.CLOSE),
    (3, DateQuality.CLOSE),
    (-3, DateQuality.CLOSE),
    (4, DateQuality.WIDE),
    (14, DateQuality.WIDE),
    (-30, DateQuality.WIDE),
])
def test_date_quality_grading(gap, expected):
    assert date_quality(gap) == expected


def test_date_quality_threshold_is_configurable():
    assert date_quality(5, close_days=7) is DateQuality.CLOSE
    assert date_quality(5, close_days=3) is DateQuality.WIDE


def test_amount_memo_grades_a_small_gap_close():
    g = make_file(Side.GL, [(10, 5000, "Inv 7")])
    b = make_file(Side.BANK, [(8, 5000, "Inv 7")])
    p = amount_memo(g.rows, b.rows).proposals[0]
    assert p.date is DateQuality.CLOSE
    assert p.amount is AmountQuality.EXACT
    assert p.identity is IdentityQuality.EXACT
    assert p.note == "GL 2 days after bank"


def test_amount_memo_grades_a_large_gap_wide():
    g = make_file(Side.GL, [(2, 5000, "Inv 7")])
    b = make_file(Side.BANK, [(20, 5000, "Inv 7")])
    p = amount_memo(g.rows, b.rows).proposals[0]
    assert p.date is DateQuality.WIDE
    assert p.note == "GL 18 days before bank"


def test_amount_memo_singular_day():
    g = make_file(Side.GL, [(2, 5000, "Inv 7")])
    b = make_file(Side.BANK, [(1, 5000, "Inv 7")])
    assert amount_memo(g.rows, b.rows).proposals[0].note == "GL 1 day after bank"


def test_amount_memo_requires_the_amount():
    g = make_file(Side.GL, [(2, 5000, "Inv 7")])
    b = make_file(Side.BANK, [(2, 5001, "Inv 7")])
    assert amount_memo(g.rows, b.rows).proposals == []


def test_amount_memo_requires_the_memo():
    g = make_file(Side.GL, [(2, 5000, "Inv 7")])
    b = make_file(Side.BANK, [(2, 5000, "Inv 8")])
    assert amount_memo(g.rows, b.rows).proposals == []


def test_amount_memo_refuses_when_only_the_date_would_decide():
    """Two GL rows, same amount and memo, different dates, one deposit.

    Picking the nearer date is exactly the guess this tool declines to make.
    """
    g = make_file(Side.GL, [(2, 5000, "Inv 7"), (9, 5000, "Inv 7")])
    b = make_file(Side.BANK, [(3, 5000, "Inv 7")])
    outcome = amount_memo(g.rows, b.rows)
    assert outcome.proposals == []
    assert len(outcome.ambiguities) == 1
    assert "the date alone would decide it" in outcome.ambiguities[0].reason


def test_amount_memo_does_not_mutate_input():
    g = make_file(Side.GL, [(2, 5000, "Inv 7")])
    b = make_file(Side.BANK, [(3, 5000, "Inv 7")])
    amount_memo(g.rows, b.rows)
    assert all(r.match_id is None for r in g.rows + b.rows)


# --- the ladder on the corpus -------------------------------------------

def test_ladder_claims_every_planted_set(gl, bank):
    """Each pass claims exactly the set it was built for, and nothing else."""
    result = reconcile(gl, bank)
    assert result.pass_counts == [
        ("exact_triple", 50),      # set 1
        ("void_pairs", 2),         # sets 9 and 10, one group each
        ("amount_memo", 60),       # sets 2 and 3
        ("group_sum", 30),         # sets 6 and 7, 15 groups each way
        ("digit_core_dated", 10),  # set 4
        ("digit_core", 10),        # set 5
        ("near_amount", 5),        # set 11
    ]
    assert len(result.matches) == 167


def test_ladder_leaves_only_the_genuine_non_matches(gl, bank):
    """Set 8 is the only thing that should survive the whole ladder."""
    result = reconcile(gl, bank)
    assert len(result.unmatched_gl) == 3
    assert len(result.unmatched_bank) == 3


def test_the_survivors_are_set_eight(gl, bank):
    """Identified independently: set 8 memos are reversed names, so no digits."""
    from recon.identity import memo_digit_core

    result = reconcile(gl, bank)
    for row in result.unmatched_gl + result.unmatched_bank:
        assert memo_digit_core(row.memo) is None, row


def test_ladder_group_shapes_match_the_corpus_design(gl, bank):
    """Sets 6 and 7 planted five groups at each of sizes 2, 3 and 5, both ways."""
    result = reconcile(gl, bank)
    shapes = Counter(m.shape for m in result.matches if m.rule == "group_sum")
    assert shapes == {
        "2:1": 5, "3:1": 5, "5:1": 5,   # set 6, GL many
        "1:2": 5, "1:3": 5, "1:5": 5,   # set 7, bank many
    }


def test_ladder_quality_axes_are_populated_as_designed(gl, bank):
    result = reconcile(gl, bank)
    by_amount = Counter(m.amount for m in result.matches)
    assert by_amount[AmountQuality.SUM] == 30    # group matches
    assert by_amount[AmountQuality.NEAR] == 5    # set 11 penny drifts
    assert by_amount[AmountQuality.EXACT] == 132
    identity = Counter(m.identity for m in result.matches)
    assert identity[IdentityQuality.SIMILAR] == 20  # sets 4 and 5
    assert identity[IdentityQuality.NONE] == 0


def test_ladder_date_grading_splits_sets_two_and_three(gl, bank):
    result = reconcile(gl, bank)
    graded = Counter(
        m.date for m in result.matches if m.rule == "amount_memo"
    )
    assert graded[DateQuality.CLOSE] == 50   # set 2, shifted 1-3 days
    assert graded[DateQuality.WIDE] == 10    # set 3, 14 days or more


def test_ladder_void_groups_are_one_sided_and_net_to_zero(gl, bank):
    result = reconcile(gl, bank)
    voids = [m for m in result.matches if m.rule == "void_pairs"]
    assert len(voids) == 2
    assert {m.shape for m in voids} == {"2:0", "0:2"}
    assert all(m.one_sided for m in voids)
    rows = {r.row_id: r for r in list(result.gl.rows) + list(result.bank.rows)}
    for m in voids:
        legs = [rows[i] for i in m.gl_ids + m.bank_ids]
        assert sum(r.amount_cents for r in legs) == 0
        assert len({r.txn_date for r in legs}) == 1
        assert len({r.memo for r in legs}) == 1


def test_ladder_finds_the_planted_void_amounts(gl, bank):
    result = reconcile(gl, bank)
    rows = {r.row_id: r for r in list(result.gl.rows) + list(result.bank.rows)}
    magnitudes = set()
    for m in result.matches:
        if m.rule == "void_pairs":
            legs = [rows[i] for i in m.gl_ids + m.bank_ids]
            magnitudes.add(max(abs(r.amount_cents) for r in legs))
    assert magnitudes == {10000, 30000}  # set 9 at 100.00, set 10 at 300.00


def test_ladder_proof_still_foots(gl, bank):
    result = reconcile(gl, bank)
    unmatched_gl = sum(r.amount_cents for r in result.unmatched_gl)
    unmatched_bank = sum(r.amount_cents for r in result.unmatched_bank)
    difference = result.gl.total_cents - result.bank.total_cents
    assert unmatched_gl - unmatched_bank + result.drift_cents == difference
    # Set 11's five penny differences, and nothing else, are absorbed as drift.
    assert result.drift_cents == -11


def test_ladder_claims_no_row_twice(gl, bank):
    result = reconcile(gl, bank)
    seen: list[str] = []
    for m in result.matches:
        seen.extend(m.gl_ids + m.bank_ids)
    assert len(seen) == len(set(seen))


def test_ladder_is_deterministic(corpus_dir):
    from recon.load import load_bank, load_gl

    def run():
        return reconcile(
            load_gl(corpus_dir / "general_ledger.csv"),
            load_bank(corpus_dir / "bank.csv"),
        )

    a, b = run(), run()
    assert [(m.match_id, m.rule, m.gl_ids, m.bank_ids, m.date) for m in a.matches] == \
           [(m.match_id, m.rule, m.gl_ids, m.bank_ids, m.date) for m in b.matches]


def test_no_ambiguities_on_this_corpus(gl, bank):
    """The corpus is deliberately unambiguous; a flag here means a pass changed."""
    assert reconcile(gl, bank).ambiguities == []


def test_pass_order_matters_and_is_load_bearing(gl, bank):
    """Running amount_memo before exact_triple changes the date grading.

    amount_memo ignores the date, so it would claim set 1 as well - correctly,
    but graded Exact by luck rather than by rule, and leaving exact_triple with
    nothing. Documented as a test because the ordering is a decision, not an
    accident.
    """
    from recon.engine import MatchPass

    reordered = [
        MatchPass("amount_memo", "", amount_memo),
        MatchPass("exact_triple", "", exact_triple),
    ]
    result = reconcile(gl, bank, passes=reordered)
    counts = dict(result.pass_counts)
    assert counts["amount_memo"] == 110  # set 1 swallowed along with 2 and 3
    assert counts["exact_triple"] == 0
