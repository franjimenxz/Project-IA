"""AC-P14-010: FAQ read-tool announcement stays inside the turn tenant."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.configuration.models import TenantConfig
from ia_mcp.mcp.registry import ToolName
from ia_mcp.skills.faq import FAQSkill
from ia_mcp.skills.registry import SkillRegistry
from ia_mcp.tenancy.models import TenantContext
from scripts.check_tenant_specific_core import find_slug_branches
from tests.unit.agent.test_context_compiler import (
    TENANT_A,
    TENANT_B,
    FakeConfigRepository,
    config_for,
    request,
    tenant_context,
)

pytestmark = [pytest.mark.security]

COMPILER_PATH = Path("src/ia_mcp/agent_runtime/context_compiler.py")
FAQ_PATH = Path("src/ia_mcp/skills/faq.py")
PROCESS_READ_CATALOG = frozenset({"appointments.search", "appointments.get"})


class RecordingConfigRepository(FakeConfigRepository):
    def __init__(self, configs: dict[UUID, TenantConfig]) -> None:
        super().__init__(configs)
        self.contexts: list[TenantContext] = []

    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None:
        self.contexts.append(context)
        return await super().get_for_runtime(context)


@pytest.mark.anyio
async def test_compile_of_tenant_a_does_not_see_enabled_tools_of_tenant_b() -> None:
    configs = RecordingConfigRepository(
        {
            TENANT_A: config_for(
                TENANT_A,
                skills=frozenset({"faq"}),
                enabled_tools=frozenset({"appointments.search"}),
            ),
            TENANT_B: config_for(
                TENANT_B,
                skills=frozenset({"faq"}),
                enabled_tools=frozenset({"appointments.get"}),
            ),
        }
    )
    compiler = ContextCompiler(
        configs=configs,
        skills=SkillRegistry(),
        tenant_tools={
            TENANT_A: frozenset({"appointments.get"}),
            TENANT_B: frozenset({"appointments.search"}),
        },
        server_tools=PROCESS_READ_CATALOG,
    )
    tenant_a = tenant_context()
    tenant_b = tenant_context(tenant_id=TENANT_B, slug="tenant-b")

    context_a = await compiler.compile(tenant_a, request(skill="faq"))
    context_b = await compiler.compile(tenant_b, request(skill="faq"))

    assert [schema.name for schema in context_a.tool_schemas] == ["appointments.search"]
    assert [schema.name for schema in context_b.tool_schemas] == ["appointments.get"]
    assert context_a.tenant_id == tenant_a.tenant_id
    assert context_b.tenant_id == tenant_b.tenant_id
    assert "appointments.get" not in context_a.model_dump_json()
    assert "appointments.search" not in context_b.model_dump_json()
    assert all(isinstance(ctx, TenantContext) for ctx in configs.contexts)
    assert [ctx.tenant_id for ctx in configs.contexts] == [TENANT_A, TENANT_B]


def test_faq_allowlist_does_not_mix_enabled_tools_across_configs() -> None:
    skill = FAQSkill()
    config_a = config_for(
        TENANT_A,
        skills=frozenset({"faq"}),
        enabled_tools=frozenset({"appointments.search", "appointments.create"}),
    )
    config_b = config_for(
        TENANT_B,
        skills=frozenset({"faq"}),
        enabled_tools=frozenset({"appointments.get", "appointments.cancel"}),
    )
    allowed_a = skill.allowed_tools(config_a)
    allowed_b = skill.allowed_tools(config_b)
    assert allowed_a == frozenset(
        {ToolName("appointments.search"), ToolName("appointments.create")}
    )
    assert allowed_b == frozenset(
        {ToolName("appointments.get"), ToolName("appointments.cancel")}
    )
    assert ToolName("appointments.get") not in allowed_a
    assert ToolName("appointments.cancel") not in allowed_a
    assert ToolName("appointments.search") not in allowed_b
    assert ToolName("appointments.create") not in allowed_b


def test_faq_and_compiler_have_no_slug_branches() -> None:
    assert find_slug_branches(COMPILER_PATH.read_text(encoding="utf-8")) == ()
    assert find_slug_branches(FAQ_PATH.read_text(encoding="utf-8")) == ()
