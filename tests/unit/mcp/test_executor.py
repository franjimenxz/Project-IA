"""ToolExecutor authorization and dispatch.

Deviation: pytest-asyncio is not installed and must not be added; tests wrap
coroutines with asyncio.run. Seed body matches the plan; the wrapper is sync.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp.executor import McpTarget, ToolCall, ToolExecutor
from ia_mcp.tenancy.models import TenantContext

TENANT_A_CTX = TenantContext(
    tenant_id=uuid4(),
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=uuid4(),
)
TENANT_B_CTX = TenantContext(
    tenant_id=uuid4(),
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=uuid4(),
)
RUN_ID = uuid4()

CATALOG = frozenset(
    {
        "appointments.search",
        "appointments.get",
        "appointments.create",
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm",
    }
)
# Tenant A enabled_tools = search/get only so create is outside the intersection.
TENANT_A_TOOLS = frozenset({"appointments.search", "appointments.get"})

SEARCH_ARGS: dict[str, Any] = {
    "specialty": "cardiologia",
    "date_from": "2026-09-01",
    "date_to": "2026-09-01",
}

SECRET_FRAGMENTS = (
    "tok-super-secret",
    "ada@example.com",
    "secret-dni-999",
    "Ada Lovelace",
    "Bearer secret-token",
    "https://internal.example/secret-mcp",
    "cred-secret-must-not-leak",
)


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def tool_call(
    name: str,
    arguments: Mapping[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> ToolCall:
    return ToolCall(
        name=name,
        arguments=arguments or {},
        idempotency_key=idempotency_key,
    )


class CapabilitySpy:
    def __init__(self) -> None:
        empty = ToolResult[list[object]](ok=True, value=[])
        self.search = AsyncMock(return_value=empty)
        self.get = AsyncMock()
        self.create = AsyncMock()
        self.cancel = AsyncMock()
        self.reschedule = AsyncMock()
        self.confirm = AsyncMock()

    def assert_not_called(self) -> None:
        self.search.assert_not_called()
        self.get.assert_not_called()
        self.create.assert_not_called()
        self.cancel.assert_not_called()
        self.reschedule.assert_not_called()
        self.confirm.assert_not_called()


class ResolverSpy:
    def __init__(self) -> None:
        self.resolve = AsyncMock(
            return_value=McpTarget(
                server_id="mcp-appointments-a",
                allowed_tools=CATALOG,
                endpoint="https://internal.example/secret-mcp",
                auth_reference="cred-secret-must-not-leak",
            )
        )

    def assert_not_called(self) -> None:
        self.resolve.assert_not_called()


def _make_executor(
    capability: CapabilitySpy,
    resolver: ResolverSpy,
    audit: Mock,
    *,
    tenant_tools: frozenset[str] = TENANT_A_TOOLS,
) -> ToolExecutor:
    return ToolExecutor(
        server=CATALOG,
        tenant=tenant_tools,
        skill=CATALOG,
        capability=capability,
        resolver=resolver,
        audit_hook=audit,
    )


@pytest.fixture
def capability_spy() -> CapabilitySpy:
    return CapabilitySpy()


@pytest.fixture
def resolver_spy() -> ResolverSpy:
    return ResolverSpy()


@pytest.fixture
def audit_spy() -> Mock:
    return Mock()


@pytest.fixture
def executor(
    capability_spy: CapabilitySpy,
    resolver_spy: ResolverSpy,
    audit_spy: Mock,
) -> ToolExecutor:
    return _make_executor(capability_spy, resolver_spy, audit_spy)


def test_forbidden_tool_never_reaches_capability(
    executor: ToolExecutor,
    capability_spy: CapabilitySpy,
    resolver_spy: ResolverSpy,
) -> None:
    async def _seed() -> None:
        result = await executor.execute(
            TENANT_A_CTX, RUN_ID, tool_call("appointments.create")
        )
        assert result.error.code == ToolErrorCode.FORBIDDEN
        capability_spy.assert_not_called()

    _run(_seed())
    resolver_spy.assert_not_called()


def test_unknown_tool_is_forbidden(
    executor: ToolExecutor,
    capability_spy: CapabilitySpy,
    resolver_spy: ResolverSpy,
) -> None:
    result = _run(
        executor.execute(TENANT_A_CTX, RUN_ID, tool_call("appointments.explode"))
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.FORBIDDEN
    assert result.error.retryable is False
    capability_spy.assert_not_called()
    resolver_spy.assert_not_called()


def test_allowed_tool_calls_capability(
    executor: ToolExecutor,
    capability_spy: CapabilitySpy,
    resolver_spy: ResolverSpy,
) -> None:
    result = _run(
        executor.execute(
            TENANT_A_CTX,
            RUN_ID,
            tool_call("appointments.search", SEARCH_ARGS),
        )
    )
    assert result.ok is True
    capability_spy.search.assert_called_once()
    tenant_arg = capability_spy.search.call_args.args[0]
    assert tenant_arg is TENANT_A_CTX
    resolver_spy.resolve.assert_awaited_once()
    assert resolver_spy.resolve.call_args.args == (TENANT_A_CTX, "appointments")


def test_capability_receives_execute_tenant_context(
    executor: ToolExecutor,
    capability_spy: CapabilitySpy,
    resolver_spy: ResolverSpy,
) -> None:
    _run(
        executor.execute(
            TENANT_B_CTX,
            RUN_ID,
            tool_call("appointments.search", SEARCH_ARGS),
        )
    )
    capability_spy.search.assert_called_once()
    tenant_arg = capability_spy.search.call_args.args[0]
    assert tenant_arg is TENANT_B_CTX
    assert tenant_arg is not TENANT_A_CTX
    assert resolver_spy.resolve.call_args.args[0] is TENANT_B_CTX


def test_mutation_passes_idempotency_key(
    capability_spy: CapabilitySpy,
    resolver_spy: ResolverSpy,
    audit_spy: Mock,
) -> None:
    capability_spy.create.return_value = ToolResult[dict[str, str]](
        ok=True,
        value={"appointment_id": "apt-1"},
    )
    exec_ = _make_executor(
        capability_spy,
        resolver_spy,
        audit_spy,
        tenant_tools=TENANT_A_TOOLS | {"appointments.create"},
    )
    payload = {
        "slot_id": "slot-1",
        "patient": {"external_patient_id": "pat-1"},
    }
    _run(
        exec_.execute(
            TENANT_A_CTX,
            RUN_ID,
            tool_call("appointments.create", payload, idempotency_key="k-1"),
        )
    )
    capability_spy.create.assert_awaited_once()
    assert capability_spy.create.call_args.kwargs["idempotency_key"] == "k-1"
    assert capability_spy.create.call_args.args[0] is TENANT_A_CTX


def test_audit_hook_contains_no_secrets(
    executor: ToolExecutor,
    audit_spy: Mock,
) -> None:
    secret_call = tool_call(
        "appointments.create",
        {
            "booking_token": "tok-super-secret",
            "authorization": "Bearer secret-token",
            "patient": {
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "document_number": "secret-dni-999",
            },
        },
        idempotency_key="k-1",
    )
    _run(executor.execute(TENANT_A_CTX, RUN_ID, secret_call))
    _run(
        executor.execute(
            TENANT_A_CTX,
            RUN_ID,
            tool_call("appointments.search", SEARCH_ARGS),
        )
    )
    assert audit_spy.call_count == 2
    blob = " ".join(_event_blob(call.args[0]) for call in audit_spy.call_args_list)
    for fragment in SECRET_FRAGMENTS:
        assert fragment not in blob
    lowered = blob.lower()
    assert "endpoint" not in lowered
    assert "auth_reference" not in lowered
    assert "credentials" not in lowered


def _event_blob(event: object) -> str:
    parts = [str(event), repr(event)]
    dump = getattr(event, "__dataclass_fields__", None)
    if dump is not None:
        for name in dump:
            parts.append(f"{name}={getattr(event, name)!r}")
    return " ".join(parts)
