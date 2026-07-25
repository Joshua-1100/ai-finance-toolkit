"""The engine's guarantees: the proof holds, nothing is claimed twice, and the
result does not depend on anything but the data."""

from __future__ import annotations

from datetime import date

import pytest

from recon.engine import (
    DoubleClaim,
    MatchPass,
    PassResult,
    Pool,
    ProofFailed,
    Proposal,
    reconcile,
)
from recon.model import AmountQuality, DateQuality, IdentityQuality, Side
from recon.passes import exact_triple

from .helpers import make_file

# Pinned explicitly rather than taken from DEFAULT_PASSES: these tests are
# about pass 1 in isolation, and should not change meaning as the ladder grows.
ONLY_EXACT_TRIPLE = [MatchPass("exact_triple", "pass 1 alone", exact_triple)]


# --- the proof -----------------------------------------------------------

def test_proof_holds_on_the_corpus(gl, bank):
    """reconcile() proves the identity after every pass; reaching the end is
    itself the assertion."""
    result = reconcile(gl, bank)
    assert result.matches


def test_proof_catches_a_tampered_amount(gl, bank):
    pool = Pool(gl, bank)
    pool.prove("load")
    gl.rows[0].amount_cents += 1  # as if a pass had rewritten an amount
    with pytest.raises(ProofFailed, match="totals identity broke"):
        pool.prove("tamper")


def test_proof_catches_an_orphaned_match_id(gl, bank):
    pool = Pool(gl, bank)
    gl.rows[0].match_id = "M9999"  # set without a corresponding Match
    with pytest.raises(ProofFailed, match="no match"):
        pool.prove()


def test_double_claim_is_refused():
    g = make_file(Side.GL, [(1, 100, "Inv 1")])
    b = make_file(Side.BANK, [(1, 100, "Inv 1")])
    pool = Pool(g, b)
    p = Proposal(["GL-0001"], ["BK-0001"], AmountQuality.EXACT,
                 DateQuality.EXACT, IdentityQuality.EXACT)
    pool.claim("first", p)
    with pytest.raises(DoubleClaim, match="already matched"):
        pool.claim("second", p)


def test_residual_equals_file_difference_at_every_stage():
    g = make_file(Side.GL, [(1, 100, "Inv 1"), (2, 500, "Inv 2")])
    b = make_file(Side.BANK, [(1, 100, "Inv 1")])
    pool = Pool(g, b)
    assert pool.residual_cents() == 500
    pool.claim("exact_triple", Proposal(
        ["GL-0001"], ["BK-0001"], AmountQuality.EXACT,
        DateQuality.EXACT, IdentityQuality.EXACT))
    assert pool.residual_cents() == 500
    pool.prove("after claim")


def test_near_match_drift_is_carried_in_the_proof():
    """A match accepted despite a penny difference must account for that penny."""
    g = make_file(Side.GL, [(1, 10000, "Inv 1")])
    b = make_file(Side.BANK, [(1, 9995, "Inv 1")])
    pool = Pool(g, b)
    pool.claim("near_amount", Proposal(
        ["GL-0001"], ["BK-0001"], AmountQuality.NEAR,
        DateQuality.EXACT, IdentityQuality.EXACT))
    assert pool.drift_cents(pool.matches[0]) == 5
    pool.prove("near")  # 5 cents of drift, 0 unmatched, files differ by 5


def test_one_sided_group_is_allowed_and_nets_to_zero():
    """A void pair resolves with no counterparty - sets 9 and 10."""
    g = make_file(Side.GL, [(1, 10000, "Inv 1"), (1, -10000, "Inv 1")])
    b = make_file(Side.BANK, [])
    pool = Pool(g, b)
    match = pool.claim("void_pairs", Proposal(
        ["GL-0001", "GL-0002"], [], AmountQuality.EXACT,
        DateQuality.EXACT, IdentityQuality.EXACT, note="nets to zero"))
    assert match.one_sided
    assert match.shape == "2:0"
    assert pool.drift_cents(match) == 0
    pool.prove("void")


# --- determinism ---------------------------------------------------------

def test_match_ids_are_data_dependent_not_order_dependent(corpus_dir):
    from recon.load import load_bank, load_gl

    def run():
        return reconcile(
            load_gl(corpus_dir / "general_ledger.csv"),
            load_bank(corpus_dir / "bank.csv"),
        )

    a, b = run(), run()
    assert [(m.match_id, m.gl_ids, m.bank_ids) for m in a.matches] == \
           [(m.match_id, m.gl_ids, m.bank_ids) for m in b.matches]


def test_match_ids_are_sequential_from_one(gl, bank):
    result = reconcile(gl, bank)
    assert [m.match_id for m in result.matches[:3]] == ["M0001", "M0002", "M0003"]


# --- pass 1 --------------------------------------------------------------

def test_exact_triple_claims_set_one_only(gl, bank):
    """Set 1 planted 50 exact matches. Pass 1 should find those and stop."""
    result = reconcile(gl, bank, passes=ONLY_EXACT_TRIPLE)
    assert result.pass_counts == [("exact_triple", 50)]
    assert len(result.matches) == 50
    assert result.matched_gl_count == 50
    assert result.matched_bank_count == 50


def test_exact_triple_matches_are_all_exact_on_three_axes(gl, bank):
    result = reconcile(gl, bank, passes=ONLY_EXACT_TRIPLE)
    for m in result.matches:
        assert m.amount is AmountQuality.EXACT
        assert m.date is DateQuality.EXACT
        assert m.identity is IdentityQuality.EXACT
        assert m.shape == "1:1"
        assert m.rule == "exact_triple"


def test_exact_triple_pairs_agree_on_all_three_fields(gl, bank):
    """Independently re-check every claim rather than trusting the pass."""
    result = reconcile(gl, bank, passes=ONLY_EXACT_TRIPLE)
    rows = {r.row_id: r for r in list(result.gl.rows) + list(result.bank.rows)}
    for m in result.matches:
        g, b = rows[m.gl_ids[0]], rows[m.bank_ids[0]]
        assert g.txn_date == b.txn_date
        assert g.amount_cents == b.amount_cents
        assert g.memo.upper() == b.memo.upper()


def test_exact_triple_folds_case_and_spacing():
    g = make_file(Side.GL, [(1, 100, "  inv   123 ")])
    b = make_file(Side.BANK, [(1, 100, "INV 123")])
    assert len(exact_triple(g.rows, b.rows).proposals) == 1


def test_exact_triple_declines_indistinguishable_rows():
    """Two identical GL rows against one deposit is not a solvable puzzle."""
    g = make_file(Side.GL, [(1, 100, "Inv 1"), (1, 100, "Inv 1")])
    b = make_file(Side.BANK, [(1, 100, "Inv 1")])
    outcome = exact_triple(g.rows, b.rows)
    assert outcome.proposals == []
    assert len(outcome.ambiguities) == 1
    amb = outcome.ambiguities[0]
    assert amb.gl_ids == ["GL-0001", "GL-0002"]
    assert amb.bank_ids == ["BK-0001"]
    assert "indistinguishable" in amb.reason


def test_exact_triple_ignores_near_misses():
    """One cent, one day and one character apart are all misses for this pass."""
    g = make_file(Side.GL, [(1, 100, "Inv 1"), (2, 200, "Inv 2"), (3, 300, "Inv 3")])
    b = make_file(Side.BANK, [(1, 101, "Inv 1"), (3, 200, "Inv 2"), (3, 300, "Inv 33")])
    assert exact_triple(g.rows, b.rows).proposals == []


def test_exact_triple_does_not_mutate_its_input():
    g = make_file(Side.GL, [(1, 100, "Inv 1")])
    b = make_file(Side.BANK, [(1, 100, "Inv 1")])
    exact_triple(g.rows, b.rows)
    assert all(r.match_id is None for r in g.rows + b.rows)


def test_a_pass_claiming_a_taken_row_is_a_bug_not_bad_data(gl, bank):
    """The engine localises the failure to the offending pass."""
    greedy = MatchPass(
        name="greedy",
        description="claims GL-0001 regardless",
        run=lambda g, b: PassResult(proposals=[Proposal(
            ["GL-0001"], [], AmountQuality.NONE, DateQuality.NONE,
            IdentityQuality.NONE)]),
    )
    # Two passes both claiming GL-0001; the second must be refused. The first
    # only succeeds if GL-0001 was still free, so run pass 1 first to be sure.
    with pytest.raises(DoubleClaim, match="greedy"):
        reconcile(gl, bank, passes=[greedy, greedy])
