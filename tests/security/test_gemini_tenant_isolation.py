"""AC-P14-010: GeminiLLM does not branch on tenant identity or leak it."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from ia_mcp.agent_runtime.models import LLMRequest
from ia_mcp.llm.gemini import GeminiLLM
from scripts.check_tenant_specific_core import find_slug_branches
from tests.unit.llm.test_gemini import (
    CORE_INSTRUCTIONS,
    TEST_API_KEY,
    RecordingTransport,
    _all_strings,
    _decision_payload,
    _part_texts,
    _request,
)

TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
SLUG_A = "tenant-a"
SLUG_B = "tenant-b"
CANARY_A_TONE = "canary-tone-tenant-a"
CANARY_A_INSTRUCTIONS = "CANARY-A-DO-NOT-LEAK-TO-B"
CANARY_A_KNOWLEDGE = "CANARY-A-EVIDENCE-HOURS"
CANARY_B_TONE = "formal"
CANARY_B_INSTRUCTIONS = (
    "No invente horarios ni especialidades que no figuren en el conocimiento."
)
CANARY_B_KNOWLEDGE = "Hours are 8 to 16."
GEMINI_PATH = Path("src/ia_mcp/llm/gemini.py")


def _request_for(
    tenant_id: UUID,
    *,
    tone: str,
    tenant_instructions: str,
    knowledge: str,
) -> LLMRequest:
    return _request(
        tenant_id=tenant_id,
        tone=tone,
        tenant_instructions=tenant_instructions,
        knowledge=(knowledge,),
    )


@pytest.mark.security
@pytest.mark.anyio
async def test_adapter_omits_tenant_id_and_slug_from_body() -> None:
    transport = RecordingTransport(_decision_payload())
    llm = GeminiLLM(transport=transport, api_key=TEST_API_KEY)
    await llm.generate(_request_for(TENANT_B, tone=CANARY_B_TONE, tenant_instructions=CANARY_B_INSTRUCTIONS, knowledge=CANARY_B_KNOWLEDGE))
    body = transport.bodies[0]
    serialized = json.dumps(body)
    joined = " ".join(_all_strings(body))
    assert str(TENANT_B) not in serialized
    assert SLUG_A not in serialized
    assert SLUG_B not in serialized
    assert "tenant_id" not in joined
    assert "tenant_slug" not in joined


@pytest.mark.security
@pytest.mark.anyio
async def test_tenant_b_body_does_not_contain_tenant_a_canaries() -> None:
    transport = RecordingTransport(_decision_payload())
    llm = GeminiLLM(transport=transport, api_key=TEST_API_KEY)
    await llm.generate(
        _request_for(
            UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            tone=CANARY_A_TONE,
            tenant_instructions=CANARY_A_INSTRUCTIONS,
            knowledge=CANARY_A_KNOWLEDGE,
        )
    )
    await llm.generate(
        _request_for(
            TENANT_B,
            tone=CANARY_B_TONE,
            tenant_instructions=CANARY_B_INSTRUCTIONS,
            knowledge=CANARY_B_KNOWLEDGE,
        )
    )
    assert len(transport.bodies) == 2
    body_a, body_b = transport.bodies
    serialized_b = json.dumps(body_b)
    assert CANARY_A_TONE not in serialized_b
    assert CANARY_A_INSTRUCTIONS not in serialized_b
    assert CANARY_A_KNOWLEDGE not in serialized_b
    serialized_a = json.dumps(body_a)
    assert CANARY_B_TONE not in serialized_a or CANARY_B_TONE == CANARY_A_TONE
    assert CANARY_A_INSTRUCTIONS in serialized_a
    assert CANARY_B_INSTRUCTIONS in serialized_b


@pytest.mark.security
@pytest.mark.anyio
async def test_two_tenants_share_the_same_field_mapping() -> None:
    transport = RecordingTransport(_decision_payload())
    llm = GeminiLLM(transport=transport, api_key=TEST_API_KEY)
    request_a = _request_for(
        UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        tone=CANARY_A_TONE,
        tenant_instructions=CANARY_A_INSTRUCTIONS,
        knowledge=CANARY_A_KNOWLEDGE,
    )
    request_b = _request_for(
        TENANT_B,
        tone=CANARY_B_TONE,
        tenant_instructions=CANARY_B_INSTRUCTIONS,
        knowledge=CANARY_B_KNOWLEDGE,
    )
    await llm.generate(request_a)
    await llm.generate(request_b)
    body_a, body_b = transport.bodies
    assert set(body_a) == set(body_b)
    assert body_a["systemInstruction"] == {"parts": [{"text": CORE_INSTRUCTIONS}]}
    assert body_b["systemInstruction"] == {"parts": [{"text": CORE_INSTRUCTIONS}]}
    texts_a = _part_texts(body_a)
    texts_b = _part_texts(body_b)
    assert any(CANARY_A_TONE in text for text in texts_a)
    assert any(CANARY_B_TONE in text for text in texts_b)
    assert any(CANARY_A_INSTRUCTIONS in text for text in texts_a)
    assert any(CANARY_B_INSTRUCTIONS in text for text in texts_b)
    assert any("EVIDENCE" in text for text in texts_a)
    assert any("EVIDENCE" in text for text in texts_b)
    assert not any(
        CORE_INSTRUCTIONS in text and CANARY_A_INSTRUCTIONS in text for text in texts_a
    )
    assert not any(
        CORE_INSTRUCTIONS in text and CANARY_B_INSTRUCTIONS in text for text in texts_b
    )
    tools_a = body_a["tools"]
    tools_b = body_b["tools"]
    assert tools_a == tools_b


@pytest.mark.security
def test_gemini_adapter_has_no_slug_branches() -> None:
    source = GEMINI_PATH.read_text(encoding="utf-8")
    assert find_slug_branches(source) == ()
    assert "tenant_slug" not in source
    assert "if tenant_id" not in source
    assert "match tenant_id" not in source
