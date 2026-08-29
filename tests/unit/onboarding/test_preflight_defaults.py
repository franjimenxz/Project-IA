"""What the composition root's preflight defaults do once the router is mounted.

Characterization of a documented residual: `default_preflight_checks` builds
fail-closed stand-ins for the ports that have no adapter in `src/`, so HTTP
activation stays refused. Nothing here forces the checks green with a fake.

No PostgreSQL is required: only the checks that open no session are run, and
`create_async_engine` never connects while the graph is being built.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from ia_mcp.configuration.adapters.environment_secrets import (
    EnvironmentSecretResolver,
)
from ia_mcp.onboarding.activation import assert_report_allows_activation
from ia_mcp.onboarding.commands import OnboardingError
from ia_mcp.onboarding.preflight import (
    PREFLIGHT_CHECK_NAMES,
    CheckOutcome,
    PreflightCheckPort,
    ResolvableSecretReferences,
    SecretResolvabilityCheck,
    default_preflight_checks,
    report_from_outcomes,
)
from ia_mcp.tenancy.models import TenantContext

# Port 1 is never a PostgreSQL listener; nothing may connect while checking.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://ia_mcp@127.0.0.1:1/ia_mcp_preflight"
TENANT_ID = UUID("33333333-3333-3333-3333-333333333333")
CONTENT_HASH = "a" * 64
CONFIG_HASH = "b" * 64
REFERENCE = "sm://tenant-b/mcp/appointments"
VARIABLE = "IA_MCP_SECRET_TENANT_B_MCP_APPOINTMENTS"

# Checks whose port has no adapter in `src/` and that hold no database session.
SESSIONLESS_FAIL_CLOSED = {
    "mcp_health": "mcp_unhealthy",
    "eval_smoke": "eval_smoke_failed",
    "observability": "observability_unavailable",
}


def _tenant() -> TenantContext:
    return TenantContext(
        tenant_id=TENANT_ID,
        tenant_slug="tenant-b",
        config_version=1,
        correlation_id=uuid4(),
    )


def _defaults() -> dict[str, PreflightCheckPort]:
    engine = create_async_engine(UNREACHABLE_DATABASE_URL)
    return {check.name: check for check in default_preflight_checks(engine)}


def test_defaults_cover_every_required_check() -> None:
    assert tuple(_defaults()) == PREFLIGHT_CHECK_NAMES


def test_the_fail_closed_secret_port_is_replaceable_by_the_real_resolver() -> None:
    """The default refuses every reference; a wired resolver answers for real."""
    default = _defaults()["secrets_resolvable"]
    assert isinstance(default, SecretResolvabilityCheck)
    assert asyncio.run(default.secrets.resolvable(_tenant(), REFERENCE)) is False
    wired = SecretResolvabilityCheck(
        create_async_engine(UNREACHABLE_DATABASE_URL),
        ResolvableSecretReferences(EnvironmentSecretResolver({VARIABLE: "canary"})),
    )
    assert asyncio.run(wired.secrets.resolvable(_tenant(), REFERENCE)) is True
    assert asyncio.run(wired.secrets.resolvable(_tenant(), "sm://tenant-b/absent")) is False


def test_ports_without_an_adapter_fail_closed() -> None:
    checks = _defaults()
    tenant = _tenant()
    for name, code in SESSIONLESS_FAIL_CLOSED.items():
        outcome = asyncio.run(checks[name].run(tenant))
        assert outcome.passed is False, name
        assert outcome.code == code
        assert outcome.severity == "critical"


def test_activation_stays_refused_while_those_ports_fail_closed() -> None:
    outcomes = tuple(
        CheckOutcome(
            name=name,
            passed=name not in SESSIONLESS_FAIL_CLOSED,
            severity="critical",
            code=SESSIONLESS_FAIL_CLOSED.get(name, "ok"),
            message="ok",
        )
        for name in PREFLIGHT_CHECK_NAMES
    )
    report = report_from_outcomes(
        tenant_id=TENANT_ID,
        content_hash=CONTENT_HASH,
        config_hash=CONFIG_HASH,
        checks=outcomes,
    )
    assert report.passed is False
    with pytest.raises(OnboardingError) as refused:
        assert_report_allows_activation(
            report,
            content_hash=CONTENT_HASH,
            config_hash=CONFIG_HASH,
        )
    assert refused.value.code == "preflight_failed"
