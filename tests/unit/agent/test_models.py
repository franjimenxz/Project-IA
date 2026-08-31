from __future__ import annotations

from dataclasses import fields
from typing import get_args
from uuid import UUID

import pytest

from ia_mcp.agent_runtime.models import AnswerKind, LLMDecision, LLMRequest
from ia_mcp.agent_runtime.ports import FakeLLM

TENANT = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _request(**overrides: object) -> LLMRequest:
    payload: dict[str, object] = {
        "tenant_id": TENANT,
        "skill": "faq",
        "query": "hours",
        "instructions": "core-v1: follow the selected skill.",
        "knowledge": (),
        "history": (),
        "allowed_source_ids": (),
    }
    payload.update(overrides)
    return LLMRequest(**payload)  # type: ignore[arg-type]


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


def test_answer_kind_members_are_unchanged() -> None:
    assert get_args(AnswerKind) == ("answer", "clarify", "insufficient", "handoff")


@pytest.mark.anyio
async def test_production_fake_llm_still_ignores_profile_fields() -> None:
    llm = FakeLLM(LLMDecision(kind="answer", text="ok", source_ids=()))
    decision = await llm.generate(
        _request(tone="formal", tenant_instructions="Stay factual.")
    )
    assert decision.kind == "answer"
    assert decision.text == "ok"
    assert decision.source_ids == ()
