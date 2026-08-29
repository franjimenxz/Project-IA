"""What wiring the real resolver does to preflight (ADR-007).

`secrets_resolvable` used to be a constant refusal. With
`ResolvableSecretReferences` over `EnvironmentSecretResolver` it reports what
the process can actually reach: it passes when every reference the tenant
declared is exported, and fails closed — without naming a value — when one is
missing. The other fail-closed ports are untouched, so a full report still does
not pass; this suite asserts the one check that changed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from ia_mcp.configuration.adapters.environment_secrets import EnvironmentSecretResolver
from ia_mcp.onboarding.commands import Principal, load_tenant_package
from ia_mcp.onboarding.preflight import (
    ResolvableSecretReferences,
    SecretResolvabilityCheck,
)
from ia_mcp.onboarding.service import TenantOnboardingService, tenant_context_for
from ia_mcp.onboarding.validator import validate_package
from tests.fixtures.database import DATABASE_URL
from tests.unit.onboarding.helpers import write_package

ROOT = Path(__file__).resolve().parents[3]

PLATFORM = Principal(
    principal_id=UUID("11111111-1111-1111-1111-111111111111"),
    roles=frozenset({"platform_admin"}),
)
CHANNEL_REFERENCE = "sm://tenant-b/channel/simulated"
MCP_REFERENCE = "sm://tenant-b/mcp/appointments"
CHANNEL_VARIABLE = "IA_MCP_SECRET_TENANT_B_CHANNEL_SIMULATED"
MCP_VARIABLE = "IA_MCP_SECRET_TENANT_B_MCP_APPOINTMENTS"
CHANNEL_VALUE = "canary-channel-secret-must-not-appear"
MCP_VALUE = "canary-mcp-secret-must-not-appear"


def _reset_schema() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    alembic_cfg = Config(str(ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(alembic_cfg, "head")


def _package(root: Path) -> Path:
    """The default synthetic package: it declares exactly the two references."""
    return write_package(root)


def _check(engine: AsyncEngine, environ: dict[str, str]) -> SecretResolvabilityCheck:
    return SecretResolvabilityCheck(
        engine, ResolvableSecretReferences(EnvironmentSecretResolver(environ))
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    _reset_schema()
    db = create_async_engine(DATABASE_URL)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.mark.anyio
@pytest.mark.integration
async def test_exported_references_pass_and_a_missing_one_fails_closed(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    service = TenantOnboardingService(engine)
    provisioned = await service.provision(
        load_tenant_package(_package(tmp_path / "b")), PLATFORM
    )
    tenant = tenant_context_for(provisioned)
    complete = {CHANNEL_VARIABLE: CHANNEL_VALUE, MCP_VARIABLE: MCP_VALUE}
    passed = await _check(engine, complete).run(tenant)
    partial = await _check(engine, {CHANNEL_VARIABLE: CHANNEL_VALUE}).run(tenant)
    none = await _check(engine, {}).run(tenant)
    assert passed.passed is True
    assert passed.code == "ok"
    assert partial.passed is False
    assert partial.code == "secret_unresolved"
    assert none.passed is False
    assert none.code == "secret_unresolved"
    rendered = str(passed) + str(partial) + str(none)
    assert CHANNEL_VALUE not in rendered
    assert MCP_VALUE not in rendered


@pytest.mark.anyio
@pytest.mark.integration
async def test_a_wired_resolver_does_not_make_the_report_pass(
    tmp_path: Path, engine: AsyncEngine
) -> None:
    """The remaining fail-closed ports still refuse activation."""
    service = TenantOnboardingService(
        engine,
        checks=(
            *(
                check
                for check in TenantOnboardingService(engine).preflight_checks
                if check.name != "secrets_resolvable"
            ),
            _check(engine, {CHANNEL_VARIABLE: CHANNEL_VALUE, MCP_VARIABLE: MCP_VALUE}),
        ),
    )
    root = _package(tmp_path / "b")
    provisioned = await service.provision(load_tenant_package(root), PLATFORM)
    content_hash = validate_package(root).content_hash
    assert content_hash is not None
    report = await service.preflight(
        tenant_context_for(provisioned), content_hash=content_hash
    )
    outcomes = {item.name: item for item in report.checks}
    assert outcomes["secrets_resolvable"].passed is True
    assert report.passed is False
    # `retrieval_canary` fails on data (nothing is published yet); the other
    # three fail because their port still has no adapter in `src/`.
    assert {name for name, item in outcomes.items() if not item.passed} == {
        "retrieval_canary",
        "mcp_health",
        "eval_smoke",
        "observability",
    }
