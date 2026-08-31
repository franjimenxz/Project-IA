from __future__ import annotations

import asyncio
from dataclasses import fields
from typing import get_args, get_type_hints
from uuid import UUID

import pytest

from ia_mcp.agent_runtime.models import (
    AgentTurnResult,
    AnswerKind,
    LLMDecision,
    LLMRequest,
    LLMTurnDecision,
    ToolCallProposal,
    ToolObservation,
)
from ia_mcp.agent_runtime.ports import FakeLLM, LLMPort

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _alias_args(alias: object) -> tuple[object, ...]:
    return get_args(getattr(alias, "__value__", alias))


def _request(**overrides: object) -> LLMRequest:
    payload: dict[str, object] = {
        "tenant_id": TENANT_A,
        "skill": "faq",
        "query": "cual es el horario?",
        "instructions": "core-v1",
        "knowledge": (),
        "history": (),
        "allowed_source_ids": (),
    }
    payload.update(overrides)
    return LLMRequest(**payload)  # type: ignore[arg-type]


def test_answer_kind_remains_terminal_only() -> None:
    kinds = set(_alias_args(AnswerKind))
    assert kinds == {"answer", "clarify", "insufficient", "handoff"}
    assert "tool_call" not in kinds


def test_tool_call_proposal_is_valid_llm_turn_decision() -> None:
    proposal = ToolCallProposal(
        name="appointments.search",
        arguments={"specialty": "cardiologia"},
    )
    members = _alias_args(LLMTurnDecision)
    assert ToolCallProposal in members
    assert isinstance(proposal, members)


def test_llm_decision_is_still_valid_llm_turn_decision() -> None:
    decision = LLMDecision(kind="answer", text="Hours are 8 to 16.", source_ids=("kb-a-hours",))
    members = _alias_args(LLMTurnDecision)
    assert LLMDecision in members
    assert isinstance(decision, members)


def test_llm_request_accepts_tool_results_and_defaults_empty() -> None:
    request = _request()
    assert request.tool_results == ()
    observation = ToolObservation(name="appointments.search", ok=True, value={"count": 0})
    with_results = _request(tool_results=(observation,))
    assert with_results.tool_results == (observation,)


def test_llm_request_declares_additive_profile_fields() -> None:
    names = {item.name for item in fields(LLMRequest)}
    assert "tone" in names
    assert "tenant_instructions" in names


def test_llm_request_defaults_leave_profile_empty() -> None:
    request = _request()
    assert request.tone == ""
    assert request.tenant_instructions is None


def test_llm_request_accepts_tone_and_tenant_instructions() -> None:
    request = _request(tone="formal", tenant_instructions="Stay factual.")
    assert request.tone == "formal"
    assert request.tenant_instructions == "Stay factual."


def test_agent_turn_result_tool_calls_default_and_tool_names_unchanged() -> None:
    result = AgentTurnResult(
        kind="answer",
        text="Hours are 8 to 16.",
        source_ids=("kb-a-hours",),
        tenant_id=TENANT_A,
        run_id=None,
        trajectory=("receive", "search", "compile", "generate", "policy"),
        tool_names=("appointments.search",),
    )
    assert result.tool_names == ("appointments.search",)
    assert result.tool_calls == ()


def test_fake_llm_returning_decision_remains_valid_llm_port() -> None:
    decision = LLMDecision(kind="answer", text="Hours are 8 to 16.", source_ids=("kb-a-hours",))
    llm = FakeLLM(decision)
    returned = asyncio.run(llm.generate(_request()))
    assert returned is decision
    assert isinstance(returned, LLMDecision)
    return_annotation = get_type_hints(LLMPort.generate)["return"]
    assert return_annotation is LLMTurnDecision
    members = _alias_args(return_annotation)
    assert LLMDecision in members
    assert ToolCallProposal in members


@pytest.mark.anyio
async def test_production_fake_llm_still_ignores_profile_fields() -> None:
    llm = FakeLLM(LLMDecision(kind="answer", text="ok", source_ids=()))
    decision = await llm.generate(
        _request(tone="formal", tenant_instructions="Stay factual.")
    )
    assert isinstance(decision, LLMDecision)
    assert decision.kind == "answer"
    assert decision.text == "ok"
    assert decision.source_ids == ()
