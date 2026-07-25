"""The model layer.

Every test here runs offline against a fake client. A test suite that needs an
API key is a test suite people stop running.

The properties worth pinning are not "the model gives good answers" - that is
not testable and not the point. They are the guarantees that make the layer
safe: it cannot make a match, it cannot invent a value, and it cannot break a
reconciliation that already succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from recon.engine import reconcile
from recon.explain import (
    CAUSES,
    CHECKS,
    DEFAULT_MODEL,
    EXPLAIN_TOOL,
    ExplainUnavailable,
    attach,
    build_prompt,
    explain_ambiguities,
    explain_one,
)
from recon.load import load_bank, load_gl


# --- fakes ---------------------------------------------------------------

@dataclass
class FakeBlock:
    type: str
    name: str = ""
    input: dict | None = None
    text: str = ""


@dataclass
class FakeResponse:
    content: list
    stop_reason: str = "tool_use"


class FakeClient:
    """Records the requests it was given and replays canned responses."""

    def __init__(self, responses: list | None = None) -> None:
        self.requests: list[dict] = []
        self._responses = responses
        self.messages = self  # so client.messages.create(...) resolves here

    def create(self, **kwargs) -> Any:
        self.requests.append(kwargs)
        if self._responses:
            reply = self._responses.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        return FakeResponse([FakeBlock(
            type="tool_use",
            name="explain_ambiguity",
            input={
                "summary": "Two ledger lines carry the same reference.",
                "likely_cause": "duplicate_entry",
                "suggested_check": "check_for_duplicate_payment",
            },
        )])


@pytest.fixture
def ambiguous(corpus_dir):
    """The fixture corpus built to trigger every ambiguity the engine records."""
    return reconcile(
        load_gl(corpus_dir / "ambiguous_gl.csv"),
        load_bank(corpus_dir / "ambiguous_bank.csv"),
    )


# --- the fixture corpus itself ------------------------------------------

def test_fixture_produces_ambiguities_from_every_pass(ambiguous):
    """If a pass stops declining, this test says so before the demo does."""
    passes = {a.pass_name for a in ambiguous.ambiguities}
    assert passes == {
        "exact_triple", "void_pairs", "amount_memo",
        "group_sum", "digit_core_dated", "digit_core", "near_amount",
    }
    assert ambiguous.matches == []


# --- the schema is the guarantee ----------------------------------------

def test_tool_is_strict_and_closed():
    """`strict` plus `additionalProperties: false` is what makes the enums real."""
    assert EXPLAIN_TOOL["strict"] is True
    schema = EXPLAIN_TOOL["input_schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"summary", "likely_cause", "suggested_check"}
    assert set(schema["properties"]) == set(schema["required"])


def test_schema_offers_no_way_to_choose_a_match():
    """The safety property, stated as a test.

    There is no field for a row id, a pairing, a match, or a verdict - so no
    response the model could produce would resolve an ambiguity.
    """
    fields = set(EXPLAIN_TOOL["input_schema"]["properties"])
    for forbidden in (
        "match", "matches", "pairing", "gl_id", "bank_id", "row_id",
        "resolution", "verdict", "amount", "correct_pair", "decision",
    ):
        assert forbidden not in fields


def test_enums_are_the_documented_lists():
    props = EXPLAIN_TOOL["input_schema"]["properties"]
    assert props["likely_cause"]["enum"] == list(CAUSES)
    assert props["suggested_check"]["enum"] == list(CHECKS)


# --- the request ---------------------------------------------------------

def test_request_forces_the_tool(ambiguous):
    client = FakeClient()
    explain_one(ambiguous.ambiguities[0], ambiguous, client)
    sent = client.requests[0]
    assert sent["tool_choice"] == {"type": "tool", "name": "explain_ambiguity"}
    assert sent["tools"] == [EXPLAIN_TOOL]
    assert sent["model"] == DEFAULT_MODEL


def test_prompt_carries_the_rows_as_delimited_data(ambiguous):
    amb = next(a for a in ambiguous.ambiguities if a.pass_name == "exact_triple")
    prompt = build_prompt(amb, ambiguous)
    assert "<candidates>" in prompt and "</candidates>" in prompt
    for row_id in amb.gl_ids + amb.bank_ids:
        assert row_id in prompt
    assert "exact_triple" in prompt
    assert amb.reason in prompt


def test_prompt_includes_the_amounts_and_memos(ambiguous):
    amb = next(a for a in ambiguous.ambiguities if a.pass_name == "near_amount")
    prompt = build_prompt(amb, ambiguous)
    assert "500.05" in prompt and "500.03" in prompt and "500.00" in prompt
    assert "Inv 555" in prompt


def test_one_call_per_ambiguity(ambiguous):
    client = FakeClient()
    found = explain_ambiguities(ambiguous, client=client)
    assert len(client.requests) == len(ambiguous.ambiguities)
    assert len(found) == len(ambiguous.ambiguities)


def test_limit_caps_the_calls(ambiguous):
    client = FakeClient()
    found = explain_ambiguities(ambiguous, client=client, limit=2)
    assert len(client.requests) == 2
    assert len(found) == 2


def test_explanations_bind_to_their_ambiguity_by_position(ambiguous):
    """Attribution never depends on anything the model returned."""
    client = FakeClient()
    found = explain_ambiguities(ambiguous, client=client)
    for amb, exp in zip(ambiguous.ambiguities, found):
        assert exp.pass_name == amb.pass_name
        assert exp.key == amb.key
        assert exp.gl_ids == amb.gl_ids
        assert exp.bank_ids == amb.bank_ids


# --- validation on arrival ----------------------------------------------

@pytest.mark.parametrize("payload,fragment", [
    ({"summary": "", "likely_cause": "timing",
      "suggested_check": "confirm_with_bank"}, "empty summary"),
    ({"summary": "x", "likely_cause": "made_up",
      "suggested_check": "confirm_with_bank"}, "not one of the allowed"),
    ({"summary": "x", "likely_cause": "timing",
      "suggested_check": "delete_the_ledger"}, "not one of the allowed"),
])
def test_out_of_range_values_are_rejected(ambiguous, payload, fragment):
    """strict:true should prevent this. Verified anyway, never trusted."""
    client = FakeClient([FakeResponse([FakeBlock(
        type="tool_use", name="explain_ambiguity", input=payload,
    )])])
    with pytest.raises(ExplainUnavailable, match=fragment):
        explain_one(ambiguous.ambiguities[0], ambiguous, client)


def test_a_text_reply_instead_of_a_tool_call_is_an_error(ambiguous):
    client = FakeClient([FakeResponse(
        [FakeBlock(type="text", text="I think GL-0001 matches BK-0001.")],
        stop_reason="end_turn",
    )])
    with pytest.raises(ExplainUnavailable, match="no explanation returned"):
        explain_one(ambiguous.ambiguities[0], ambiguous, client)


def test_an_unexpected_tool_is_an_error(ambiguous):
    client = FakeClient([FakeResponse([FakeBlock(
        type="tool_use", name="apply_match", input={"gl": "GL-0001"},
    )])])
    with pytest.raises(ExplainUnavailable, match="unexpected tool"):
        explain_one(ambiguous.ambiguities[0], ambiguous, client)


def test_a_refusal_is_reported_plainly(ambiguous):
    client = FakeClient([FakeResponse([], stop_reason="refusal")])
    with pytest.raises(ExplainUnavailable, match="declined"):
        explain_one(ambiguous.ambiguities[0], ambiguous, client)


# --- failure never propagates ------------------------------------------

def test_a_failed_call_is_recorded_not_raised(ambiguous):
    """The recon is already finished and proved. Losing an explanation is all
    a failure here is allowed to cost."""
    responses: list = [RuntimeError("connection reset")]
    responses += [None] * (len(ambiguous.ambiguities) - 1)
    client = FakeClient([r for r in responses if r is not None])

    found = explain_ambiguities(ambiguous, client=client)
    assert len(found) == len(ambiguous.ambiguities)
    assert found[0].failed is True
    assert "connection reset" in found[0].summary
    # And it kept going.
    assert any(not e.failed for e in found[1:])


def test_a_failure_still_yields_valid_enum_values(ambiguous):
    client = FakeClient([RuntimeError("boom")])
    found = explain_ambiguities(ambiguous, client=client, limit=1)
    assert found[0].likely_cause in CAUSES
    assert found[0].suggested_check in CHECKS


def test_every_call_failing_leaves_the_result_untouched(ambiguous):
    before = [(m.match_id, m.gl_ids, m.bank_ids) for m in ambiguous.matches]
    client = FakeClient([RuntimeError("boom")] * len(ambiguous.ambiguities))
    explain_ambiguities(ambiguous, client=client)
    assert [(m.match_id, m.gl_ids, m.bank_ids) for m in ambiguous.matches] == before


def test_explaining_does_not_alter_matches_or_rows(gl, bank):
    """The model layer is strictly additive - it must not touch the recon."""
    from .helpers import make_file  # noqa: F401  (import shape check only)

    result = reconcile(gl, bank)
    snapshot = (
        [(m.match_id, m.rule, m.gl_ids, m.bank_ids) for m in result.matches],
        [r.match_id for r in result.gl.rows],
        [r.match_id for r in result.bank.rows],
        result.drift_cents,
    )
    # No ambiguities on the real corpus, so this returns immediately - which is
    # itself the assertion that the layer is a no-op when there is nothing to say.
    assert explain_ambiguities(result, client=FakeClient()) == []
    assert snapshot == (
        [(m.match_id, m.rule, m.gl_ids, m.bank_ids) for m in result.matches],
        [r.match_id for r in result.gl.rows],
        [r.match_id for r in result.bank.rows],
        result.drift_cents,
    )


def test_no_ambiguities_means_no_calls(gl, bank):
    client = FakeClient()
    assert explain_ambiguities(reconcile(gl, bank), client=client) == []
    assert client.requests == []


# --- attach --------------------------------------------------------------

def test_attach_keys_on_pass_and_key(ambiguous):
    found = explain_ambiguities(ambiguous, client=FakeClient())
    index = attach(ambiguous, found)
    for amb in ambiguous.ambiguities:
        assert f"{amb.pass_name}|{amb.key}" in index


def test_labels_are_human_readable(ambiguous):
    found = explain_ambiguities(ambiguous, client=FakeClient(), limit=1)
    assert found[0].cause_label == "duplicate entry"
    assert found[0].check_label == "check for duplicate payment"


# --- missing prerequisites ----------------------------------------------

def test_missing_sdk_is_a_sentence_not_a_traceback(ambiguous, monkeypatch):
    """Setting the module to None makes `import anthropic` raise ImportError,
    so this holds whether or not the SDK is installed here."""
    import sys

    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ExplainUnavailable, match="pip install anthropic"):
        explain_ambiguities(ambiguous)


def test_missing_api_key_is_a_sentence_not_a_traceback(ambiguous, monkeypatch):
    """Stub the SDK so this tests the key branch, not the import branch."""
    import sys
    import types

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(
        Anthropic=lambda: FakeClient()
    ))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(ExplainUnavailable, match="ANTHROPIC_API_KEY"):
        explain_ambiguities(ambiguous)


def test_client_is_built_when_prerequisites_are_present(ambiguous, monkeypatch):
    import sys
    import types

    built = FakeClient()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(
        Anthropic=lambda: built
    ))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    found = explain_ambiguities(ambiguous, limit=1)
    assert len(found) == 1
    assert not found[0].failed
    assert len(built.requests) == 1
