from __future__ import annotations

from uuid import UUID

import pytest

from ia_mcp.agent_runtime.context_compiler import ContextCompiler
from ia_mcp.agent_runtime.context_models import ContextRequest, KnowledgeHit
from ia_mcp.configuration.models import (
    AgentConfig,
    McpConfig,
    TenantConfig,
)
from ia_mcp.skills.registry import SkillNotAuthorized, SkillRegistry
from ia_mcp.tenancy.models import TenantContext

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def tenant_context(*, tenant_id: UUID = TENANT_A, slug: str = "tenant-a") -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id,
        tenant_slug=slug,
        config_version=1,
        correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
    )


def config_for(
    tenant_id: UUID,
    *,
    skills: frozenset[str],
    tone: str = "cordial",
) -> TenantConfig:
    return TenantConfig(
        tenant_id=tenant_id,
        version=1,
        agent=AgentConfig(tone=tone),
        enabled_skills=skills,
        mcp=McpConfig(credentials_reference="secret://mcp/tenant"),
    )


class FakeConfigRepository:
    def __init__(self, configs: dict[UUID, TenantConfig]) -> None:
        self._configs = configs

    async def get_for_runtime(self, context: TenantContext) -> TenantConfig | None:
        config = self._configs.get(context.tenant_id)
        if config is None or int(config.version) != context.config_version:
            return None
        return config


def request(*, skill: str, **kwargs: object) -> ContextRequest:
    return ContextRequest(skill=skill, **kwargs)  # type: ignore[arg-type]


@pytest.fixture
def tenant_a() -> TenantContext:
    return tenant_context()


@pytest.fixture
def compiler() -> ContextCompiler:
    configs = FakeConfigRepository(
        {
            TENANT_A: config_for(TENANT_A, skills=frozenset({"faq"})),
            TENANT_B: config_for(
                TENANT_B,
                skills=frozenset({"faq", "appointments"}),
                tone="formal",
            ),
        }
    )
    tenant_tools = {
        TENANT_A: frozenset({"appointments.search"}),
        TENANT_B: frozenset({"appointments.search", "appointments.create"}),
    }
    return ContextCompiler(
        configs=configs,
        skills=SkillRegistry(),
        tenant_tools=tenant_tools,
    )


@pytest.mark.anyio
async def test_compiler_excludes_disabled_tools(compiler, tenant_a):
    context = await compiler.compile(tenant_a, request(skill="faq"))
    assert context.tool_schemas == ()
    assert "credentials_reference" not in context.model_dump_json()


@pytest.mark.anyio
async def test_compiler_omits_full_config_and_only_keeps_pertinent_policy(
    compiler: ContextCompiler, tenant_a: TenantContext
) -> None:
    context = await compiler.compile(tenant_a, request(skill="faq"))
    dumped = context.model_dump()
    assert "enabled_skills" not in dumped
    assert "mcp" not in dumped
    assert dumped["policies"]["agent"]["tone"] == "cordial"
    assert "credentials_reference" not in context.model_dump_json()
    assert context.tenant_id == tenant_a.tenant_id
    assert context.config_version == tenant_a.config_version


@pytest.mark.anyio
async def test_disabled_skill_is_not_compiled(
    compiler: ContextCompiler, tenant_a: TenantContext
) -> None:
    with pytest.raises(SkillNotAuthorized):
        await compiler.compile(tenant_a, request(skill="appointments"))


@pytest.mark.anyio
async def test_appointments_skill_emits_only_authorized_tool_schemas() -> None:
    tenant_b = tenant_context(tenant_id=TENANT_B, slug="tenant-b")
    compiler = ContextCompiler(
        configs=FakeConfigRepository(
            {TENANT_B: config_for(TENANT_B, skills=frozenset({"appointments"}))}
        ),
        skills=SkillRegistry(),
        tenant_tools={TENANT_B: frozenset({"appointments.search"})},
    )
    context = await compiler.compile(tenant_b, request(skill="appointments"))
    assert [schema.name for schema in context.tool_schemas] == ["appointments.search"]
    assert "appointments.create" not in context.model_dump_json()
    assert "credentials_reference" not in context.model_dump_json()


@pytest.mark.anyio
async def test_history_and_knowledge_are_truncated_to_token_budget(
    compiler: ContextCompiler, tenant_a: TenantContext
) -> None:
    context = await compiler.compile(
        tenant_a,
        request(
            skill="faq",
            history=("alpha " * 8, "beta " * 8, "gamma " * 8),
            knowledge_hits=(KnowledgeHit(source_id="s1", text="delta " * 8),),
            token_budget=12,
        ),
    )
    serialized = " ".join((*context.history, *context.knowledge))
    assert len(serialized.split()) <= 12
    assert any("gamma" in item for item in context.history)
