from __future__ import annotations

from dataclasses import replace

import pytest

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.harness import AgentHarness
from ia_mcp.conversation.models import ReceivedMessage
from ia_mcp.skills.registry import SkillRegistry
from tests.unit.agent.test_harness import (
    TENANT_A,
    FakeConfigRepository,
    FakeConversationRepository,
    FakeKnowledge,
    FakeLLM,
    FakeRunRepository,
    config_for,
    inbound,
    tenant_a,
)


class HumanOwnedConversations(FakeConversationRepository):
    async def receive(self, tenant, message):  # type: ignore[no-untyped-def]
        received = await super().receive(tenant, message)
        return ReceivedMessage(
            conversation=replace(received.conversation, status="human_owned"),
            message=received.message,
            session=received.session,
            duplicate=received.duplicate,
        )


@pytest.mark.anyio
async def test_human_owned_blocks_automatic_mutations() -> None:
    knowledge = FakeKnowledge()
    llm = FakeLLM()
    runs = FakeRunRepository()
    configs = FakeConfigRepository({TENANT_A: config_for(TENANT_A, frozenset({"faq"}))})
    harness = AgentHarness(
        conversations=HumanOwnedConversations(),
        runs=runs,
        configs=configs,
        skills=SkillRegistry(),
        compiler=ContextCompiler(
            configs=configs,
            skills=SkillRegistry(),
            tenant_tools={TENANT_A: frozenset({"appointments.create"})},
        ),
        knowledge=knowledge,
        llm=llm,
    )
    result = await harness.handle_message(tenant_a(), inbound("create appointment"))
    assert result.kind == "handoff"
    assert result.tool_names == ()
    assert knowledge.queries == []
    assert llm.requests == []
    assert "guard" in result.trajectory
    assert "generate" not in result.trajectory
    assert runs.finished and runs.finished[0][1] == "handed_off"
