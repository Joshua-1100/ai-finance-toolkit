"""The reconciliation orchestrator.

Passes run in order of how much confidence their evidence carries. Each pass
sees only what earlier passes left behind, proposes matches, and mutates
nothing. The engine does the claiming, so that:

  - no pass can take a row another pass already took,
  - match ids are assigned in one place, in a deterministic order,
  - the totals identity is re-proved after every single pass, which localises a
    bug to the pass that caused it instead of leaving a wrong grand total.

The identity being proved is:

    GL total - Bank total  ==  sum of within-match drift  +  (unmatched GL - unmatched Bank)

Exact, Sum and void matches contribute zero drift. Only a Near match - one
accepted despite a small amount difference - contributes anything, and it
contributes precisely the difference it accepted. Integer arithmetic throughout,
so this is an equality and not an approximation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .model import (
    AmountQuality,
    DateQuality,
    IdentityQuality,
    LedgerFile,
    LedgerRow,
    Match,
    Side,
)


@dataclass(frozen=True)
class Proposal:
    """A match a pass believes in, before the engine accepts it."""

    gl_ids: list[str]
    bank_ids: list[str]
    amount: AmountQuality
    date: DateQuality
    identity: IdentityQuality
    note: str = ""

    def sort_key(self) -> tuple[str, str]:
        # Row ids are zero-padded, so lexicographic order is numeric order.
        return (
            self.gl_ids[0] if self.gl_ids else "~",
            self.bank_ids[0] if self.bank_ids else "~",
        )


@dataclass(frozen=True)
class Ambiguity:
    """Candidates a pass declined to claim because the choice was not forced.

    Recorded rather than resolved. A confident wrong match is more expensive
    than an item on a reviewer's list, because the wrong one is never revisited.
    """

    pass_name: str
    key: str
    gl_ids: list[str]
    bank_ids: list[str]
    reason: str


# A pass reads the rows still available and proposes matches. It gets plain
# lists, not the pool, so it cannot accidentally mutate state.
PassFn = Callable[[Sequence[LedgerRow], Sequence[LedgerRow]], "PassResult"]


@dataclass
class PassResult:
    proposals: list[Proposal] = field(default_factory=list)
    ambiguities: list[Ambiguity] = field(default_factory=list)


@dataclass(frozen=True)
class MatchPass:
    name: str
    description: str
    run: PassFn


class DoubleClaim(Exception):
    """A pass proposed a row that was already matched. A bug, not bad data."""


class ProofFailed(Exception):
    """The totals identity broke. A bug, not bad data."""


class Pool:
    """The rows, and which of them are still up for grabs."""

    def __init__(self, gl: LedgerFile, bank: LedgerFile) -> None:
        self.gl = gl
        self.bank = bank
        self.matches: list[Match] = []
        self.ambiguities: list[Ambiguity] = []
        self._rows: dict[str, LedgerRow] = {
            r.row_id: r for r in list(gl.rows) + list(bank.rows)
        }
        self._match_seq = 0
        # Snapshotted at construction, deliberately. Comparing live totals
        # against live totals would prove nothing: an amount rewritten mid-run
        # changes both sides of the identity equally and slips through. Held
        # against the figure the files had on arrival, it cannot.
        self._expected_difference = gl.total_cents - bank.total_cents

    def row(self, row_id: str) -> LedgerRow:
        return self._rows[row_id]

    def available(self, side: Side) -> list[LedgerRow]:
        source = self.gl.rows if side is Side.GL else self.bank.rows
        return [r for r in source if r.match_id is None]

    def claim(self, pass_name: str, proposal: Proposal) -> Match:
        rows = [self.row(i) for i in proposal.gl_ids + proposal.bank_ids]
        if not rows:
            raise DoubleClaim(f"{pass_name}: proposal claims no rows")

        already = [r.row_id for r in rows if r.match_id is not None]
        if already:
            raise DoubleClaim(
                f"{pass_name}: rows already matched: {', '.join(already)}"
            )

        self._match_seq += 1
        match = Match(
            match_id=f"M{self._match_seq:04d}",
            gl_ids=list(proposal.gl_ids),
            bank_ids=list(proposal.bank_ids),
            amount=proposal.amount,
            date=proposal.date,
            identity=proposal.identity,
            rule=pass_name,
            note=proposal.note,
        )
        for r in rows:
            r.match_id = match.match_id
        self.matches.append(match)
        return match

    def claim_all(self, pass_name: str, result: PassResult) -> list[Match]:
        # Sorted so match ids depend on the data, never on dict ordering.
        ordered = sorted(result.proposals, key=Proposal.sort_key)
        claimed = [self.claim(pass_name, p) for p in ordered]
        self.ambiguities.extend(result.ambiguities)
        return claimed

    # -- the proof -------------------------------------------------------
    def drift_cents(self, match: Match) -> int:
        """GL side minus bank side, within one match. Zero unless Near."""
        gl = sum(self.row(i).amount_cents for i in match.gl_ids)
        bank = sum(self.row(i).amount_cents for i in match.bank_ids)
        return gl - bank

    def residual_cents(self) -> int:
        """What the current state says the GL/bank difference is."""
        drift = sum(self.drift_cents(m) for m in self.matches)
        unmatched_gl = sum(r.amount_cents for r in self.available(Side.GL))
        unmatched_bank = sum(r.amount_cents for r in self.available(Side.BANK))
        return drift + unmatched_gl - unmatched_bank

    def prove(self, stage: str = "") -> None:
        """Re-derive the file difference from the match state. Must agree."""
        where = f" after {stage}" if stage else ""

        # Structural checks run first: they name the offending row, which is a
        # far more useful message than a pair of totals that fail to agree.
        claimed: dict[str, str] = {}
        for m in self.matches:
            for row_id in m.gl_ids + m.bank_ids:
                if row_id in claimed:
                    raise ProofFailed(
                        f"{row_id} claimed by both {claimed[row_id]} and {m.match_id}"
                    )
                claimed[row_id] = m.match_id
                if self.row(row_id).match_id != m.match_id:
                    raise ProofFailed(
                        f"{row_id} carries {self.row(row_id).match_id!r} but "
                        f"{m.match_id} claims it"
                    )
        for row_id, row in self._rows.items():
            if row.match_id is not None and row_id not in claimed:
                raise ProofFailed(f"{row_id} carries {row.match_id!r} with no match")

        actual = self.residual_cents()
        if self._expected_difference != actual:
            raise ProofFailed(
                f"totals identity broke{where}: files arrived differing by "
                f"{self._expected_difference} cents, match state now accounts "
                f"for {actual} cents"
            )


@dataclass
class Result:
    """The finished reconciliation."""

    gl: LedgerFile
    bank: LedgerFile
    matches: list[Match]
    ambiguities: list[Ambiguity]
    pass_counts: list[tuple[str, int]]
    _pool: Pool

    @property
    def unmatched_gl(self) -> list[LedgerRow]:
        return [r for r in self.gl.rows if r.match_id is None]

    @property
    def unmatched_bank(self) -> list[LedgerRow]:
        return [r for r in self.bank.rows if r.match_id is None]

    @property
    def matched_gl_count(self) -> int:
        return len(self.gl.rows) - len(self.unmatched_gl)

    @property
    def matched_bank_count(self) -> int:
        return len(self.bank.rows) - len(self.unmatched_bank)

    @property
    def drift_cents(self) -> int:
        return sum(self._pool.drift_cents(m) for m in self.matches)

    def match_for(self, row_id: str) -> Match | None:
        for m in self.matches:
            if row_id in m.gl_ids or row_id in m.bank_ids:
                return m
        return None


def reconcile(
    gl: LedgerFile, bank: LedgerFile, passes: Iterable[MatchPass] | None = None,
) -> Result:
    """Run the passes in order and return the reconciliation.

    Works on copies, so the caller's loaded files come back untouched and this
    can be run more than once on the same input. The reconciled rows - the ones
    carrying match_ids - are reachable through the returned Result.
    """
    from .passes import DEFAULT_PASSES

    ladder = list(passes) if passes is not None else list(DEFAULT_PASSES)
    gl, bank = gl.copy_unmatched(), bank.copy_unmatched()
    pool = Pool(gl, bank)
    pool.prove("load")

    counts: list[tuple[str, int]] = []
    for mp in ladder:
        outcome = mp.run(pool.available(Side.GL), pool.available(Side.BANK))
        claimed = pool.claim_all(mp.name, outcome)
        pool.prove(mp.name)
        counts.append((mp.name, len(claimed)))

    return Result(
        gl=gl,
        bank=bank,
        matches=pool.matches,
        ambiguities=pool.ambiguities,
        pass_counts=counts,
        _pool=pool,
    )
