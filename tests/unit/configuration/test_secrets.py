"""Environment-backed resolution of `sm://` references (ADR-007).

No PostgreSQL and no process environment are required: the adapter reads the
mapping it is handed, so every case is a pure in-memory table.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Coroutine

import pytest
from pydantic import SecretStr

from ia_mcp.configuration.adapters.environment_secrets import (
    ENVIRONMENT_PREFIX,
    EnvironmentSecretResolver,
    environment_variable_for,
)
from ia_mcp.configuration.secrets import SecretResolutionError
from ia_mcp.observability.redaction import redact

REFERENCE = "sm://tenant-b/mcp/appointments"
VARIABLE = "IA_MCP_SECRET_TENANT_B_MCP_APPOINTMENTS"
VALUE = "sk-live-canary-must-never-be-printed"


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _resolver(**environ: str) -> EnvironmentSecretResolver:
    return EnvironmentSecretResolver(environ)


def test_reference_maps_to_a_documented_variable_name() -> None:
    assert ENVIRONMENT_PREFIX == "IA_MCP_SECRET_"
    assert environment_variable_for(REFERENCE) == VARIABLE
    assert environment_variable_for("sm://admin/platform.token") == (
        "IA_MCP_SECRET_ADMIN_PLATFORM_TOKEN"
    )


def test_configured_reference_resolves_to_its_value() -> None:
    resolved = _run(_resolver(**{VARIABLE: VALUE}).resolve(REFERENCE))
    assert isinstance(resolved, SecretStr)
    assert resolved.get_secret_value() == VALUE


def test_unset_variable_fails_closed_instead_of_defaulting() -> None:
    with pytest.raises(SecretResolutionError) as refused:
        _run(_resolver().resolve(REFERENCE))
    assert refused.value.code == "secret_unresolved"
    assert refused.value.retryable is False
    assert refused.value.details["reference"] == REFERENCE


def test_blank_variable_is_not_a_value() -> None:
    with pytest.raises(SecretResolutionError) as refused:
        _run(_resolver(**{VARIABLE: "   "}).resolve(REFERENCE))
    assert refused.value.code == "secret_unresolved"


@pytest.mark.parametrize(
    "reference",
    [
        "",
        "tenant-b/mcp/appointments",
        "secret://tenant-b/mcp",
        "sm://",
        "sm:// tenant-b",
        "sm://tenant-b/../platform",
        "sm://tenant-b/mcp?x=1",
    ],
)
def test_reference_outside_the_supported_shape_is_refused(reference: str) -> None:
    with pytest.raises(SecretResolutionError) as refused:
        _run(_resolver(**{VARIABLE: VALUE}).resolve(reference))
    assert refused.value.code == "invalid_reference"


def test_a_neighbouring_variable_is_never_substituted() -> None:
    """A near-miss name must not resolve: the mapping is exact, not a search."""
    resolver = _resolver(
        IA_MCP_SECRET_TENANT_B_MCP="wrong-scope",
        IA_MCP_SECRET_TENANT_B_MCP_APPOINTMENTS_OLD="rotated-out",
    )
    with pytest.raises(SecretResolutionError):
        _run(resolver.resolve(REFERENCE))


def test_no_representation_of_a_resolved_secret_prints_its_value() -> None:
    """A resolved value only leaves through `get_secret_value`."""
    resolved = _run(_resolver(**{VARIABLE: VALUE}).resolve(REFERENCE))
    renderings = (
        str(resolved),
        repr(resolved),
        f"{resolved}",
        json.dumps(str(resolved)),
        redact(f"token={resolved}"),
    )
    for rendering in renderings:
        assert VALUE not in rendering


def test_failure_carries_neither_the_value_nor_the_variable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The refusal names the reference; nothing exposes the stored value."""
    resolver = _resolver(**{VARIABLE: VALUE})
    with pytest.raises(SecretResolutionError) as refused:
        _run(resolver.resolve("sm://tenant-b/mcp/other"))
    exception = refused.value
    with caplog.at_level(logging.ERROR):
        logging.getLogger("ia_mcp.test.secrets").error("%s %r", exception, exception)
    rendered = str(exception) + repr(exception) + caplog.text
    assert VALUE not in rendered
    assert VARIABLE not in rendered
    assert exception.safe_message == "Secret reference could not be resolved."
