"""ToolExecutor authorization and dispatch.

Deviation: pytest-asyncio is not installed and must not be added; tests wrap
coroutines with asyncio.run. Seed body matches the plan; the wrapper is sync.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Iterable, Mapping
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
CREAR_TURNO = "crear_turno"
CREAR_TURNO_ARGS: dict[str, Any] = {"slot": "manana"}
ALLOWED_MCP_HOST = "mcp.example"
ALLOWED_MCP_ENDPOINT = f"https://{ALLOWED_MCP_HOST}/sse"

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
    def __init__(
        self,
        *,
        allowed_tools: frozenset[str] = CATALOG,
        endpoint: str = "",
    ) -> None:
        self.resolve = AsyncMock(
            return_value=McpTarget(
                server_id="mcp-appointments-a",
                allowed_tools=allowed_tools,
                endpoint=endpoint,
                auth_reference="cred-secret-must-not-leak",
            )
        )

    def assert_not_called(self) -> None:
        self.resolve.assert_not_called()


class TransportSpy:
    def __init__(self) -> None:
        self.call_tool = AsyncMock(
            return_value=ToolResult[dict[str, str]](ok=True, value={"status": "ok"})
        )

    def assert_not_called(self) -> None:
        self.call_tool.assert_not_called()


def _make_executor(
    capability: CapabilitySpy,
    resolver: ResolverSpy,
    audit: Mock,
    *,
    tenant_tools: frozenset[str] = TENANT_A_TOOLS,
    server_tools: frozenset[str] = CATALOG,
    skill_tools: frozenset[str] = CATALOG,
    transport: TransportSpy | None = None,
    allowed_hosts: Iterable[str] | None = None,
) -> ToolExecutor:
    extras: dict[str, Any] = {}
    if transport is not None:
        extras["transport"] = transport
    return ToolExecutor(
        server=server_tools,
        tenant=tenant_tools,
        skill=skill_tools,
        capability=capability,
        resolver=resolver,
        audit_hook=audit,
        allowed_hosts=allowed_hosts,
        **extras,
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


def _generic_allowlists() -> dict[str, frozenset[str]]:
    tools = CATALOG | {CREAR_TURNO}
    return {
        "server_tools": tools,
        "tenant_tools": tools,
        "skill_tools": tools,
    }


def test_authorized_non_canonical_tool_calls_generic_client_not_capability(
    capability_spy: CapabilitySpy,
    audit_spy: Mock,
) -> None:
    transport = TransportSpy()
    resolver = ResolverSpy(
        allowed_tools=CATALOG | {CREAR_TURNO},
        endpoint=ALLOWED_MCP_ENDPOINT,
    )
    executor = _make_executor(
        capability_spy,
        resolver,
        audit_spy,
        transport=transport,
        allowed_hosts=(ALLOWED_MCP_HOST,),
        **_generic_allowlists(),
    )

    result = _run(
        executor.execute(
            TENANT_A_CTX,
            RUN_ID,
            tool_call(CREAR_TURNO, CREAR_TURNO_ARGS),
        )
    )

    assert result.ok is True
    assert result.value == {"status": "ok"}
    capability_spy.assert_not_called()
    transport.call_tool.assert_awaited_once()
    args = transport.call_tool.call_args
    assert args.args[0] is TENANT_A_CTX
    assert args.args[1].server_id == "mcp-appointments-a"
    assert args.args[2] == CREAR_TURNO
    assert dict(args.args[3]) == CREAR_TURNO_ARGS
    audit_spy.assert_called_once()
    event = audit_spy.call_args.args[0]
    assert event.allowed is True
    assert event.tool == CREAR_TURNO
    assert event.mcp_server_id == "mcp-appointments-a"
    blob = _event_blob(event)
    for fragment in SECRET_FRAGMENTS:
        assert fragment not in blob


@pytest.mark.parametrize(
    ("name", "arguments"),
    (
        ("appointments.search", SEARCH_ARGS),
        (CREAR_TURNO, CREAR_TURNO_ARGS),
    ),
)
def test_allowlisted_endpoint_dispatches_any_name_to_transport(
    capability_spy: CapabilitySpy,
    audit_spy: Mock,
    name: str,
    arguments: dict[str, Any],
) -> None:
    transport = TransportSpy()
    resolver = ResolverSpy(
        allowed_tools=CATALOG | {CREAR_TURNO},
        endpoint=ALLOWED_MCP_ENDPOINT,
    )
    executor = _make_executor(
        capability_spy,
        resolver,
        audit_spy,
        transport=transport,
        allowed_hosts=(ALLOWED_MCP_HOST,),
        **_generic_allowlists(),
    )

    result = _run(executor.execute(TENANT_A_CTX, RUN_ID, tool_call(name, arguments)))

    assert result.ok is True
    assert result.value == {"status": "ok"}
    capability_spy.assert_not_called()
    transport.call_tool.assert_awaited_once()
    args = transport.call_tool.call_args
    assert args.args[0] is TENANT_A_CTX
    assert args.args[1].endpoint == ALLOWED_MCP_ENDPOINT
    assert args.args[2] == name
    assert dict(args.args[3]) == arguments


def test_canonical_search_uses_capability_without_endpoint(
    capability_spy: CapabilitySpy,
    audit_spy: Mock,
) -> None:
    transport = TransportSpy()
    resolver = ResolverSpy(endpoint="")
    executor = _make_executor(
        capability_spy,
        resolver,
        audit_spy,
        transport=transport,
        allowed_hosts=(ALLOWED_MCP_HOST,),
    )

    result = _run(
        executor.execute(
            TENANT_A_CTX,
            RUN_ID,
            tool_call("appointments.search", SEARCH_ARGS),
        )
    )

    assert result.ok is True
    capability_spy.search.assert_called_once()
    assert capability_spy.search.call_args.args[0] is TENANT_A_CTX
    transport.assert_not_called()


def test_endpoint_without_allowlist_does_not_fall_to_capability(
    capability_spy: CapabilitySpy,
    audit_spy: Mock,
) -> None:
    resolver = ResolverSpy(endpoint=ALLOWED_MCP_ENDPOINT)
    executor = _make_executor(capability_spy, resolver, audit_spy)

    result = _run(
        executor.execute(
            TENANT_A_CTX,
            RUN_ID,
            tool_call("appointments.search", SEARCH_ARGS),
        )
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.FORBIDDEN
    capability_spy.assert_not_called()


def test_tenant_a_does_not_see_tenant_b_tools_or_endpoint(
    capability_spy: CapabilitySpy,
    audit_spy: Mock,
) -> None:
    transport = TransportSpy()
    resolver_a = ResolverSpy(
        allowed_tools=frozenset({"appointments.search"}),
        endpoint="https://mcp-a.example/sse",
    )
    resolver_b = ResolverSpy(
        allowed_tools=frozenset({CREAR_TURNO}),
        endpoint="https://mcp-b.example/sse",
    )
    exec_a = _make_executor(
        capability_spy,
        resolver_a,
        audit_spy,
        tenant_tools=frozenset({"appointments.search"}),
        server_tools=frozenset({"appointments.search", CREAR_TURNO}),
        skill_tools=frozenset({"appointments.search", CREAR_TURNO}),
        transport=transport,
        allowed_hosts=("mcp-a.example", "mcp-b.example"),
    )
    exec_b = _make_executor(
        capability_spy,
        resolver_b,
        audit_spy,
        tenant_tools=frozenset({CREAR_TURNO}),
        server_tools=frozenset({"appointments.search", CREAR_TURNO}),
        skill_tools=frozenset({"appointments.search", CREAR_TURNO}),
        transport=transport,
        allowed_hosts=("mcp-a.example", "mcp-b.example"),
    )

    denied = _run(
        exec_a.execute(TENANT_A_CTX, RUN_ID, tool_call(CREAR_TURNO, CREAR_TURNO_ARGS))
    )
    searched = _run(
        exec_a.execute(
            TENANT_A_CTX, RUN_ID, tool_call("appointments.search", SEARCH_ARGS)
        )
    )
    created = _run(
        exec_b.execute(TENANT_B_CTX, RUN_ID, tool_call(CREAR_TURNO, CREAR_TURNO_ARGS))
    )

    assert denied.ok is False
    assert denied.error is not None
    assert denied.error.code == ToolErrorCode.FORBIDDEN
    assert searched.ok is True
    assert created.ok is True
    endpoints = [call.args[1].endpoint for call in transport.call_tool.await_args_list]
    assert endpoints == ["https://mcp-a.example/sse", "https://mcp-b.example/sse"]
    names = [call.args[2] for call in transport.call_tool.await_args_list]
    assert names == ["appointments.search", CREAR_TURNO]
    capability_spy.assert_not_called()


def test_host_not_allowlisted_is_forbidden_without_calling_client(
    capability_spy: CapabilitySpy,
    audit_spy: Mock,
) -> None:
    transport = TransportSpy()
    resolver = ResolverSpy(
        allowed_tools=CATALOG | {CREAR_TURNO},
        endpoint="https://evil.example/sse",
    )
    executor = _make_executor(
        capability_spy,
        resolver,
        audit_spy,
        transport=transport,
        allowed_hosts=(ALLOWED_MCP_HOST,),
        **_generic_allowlists(),
    )

    result = _run(
        executor.execute(
            TENANT_A_CTX,
            RUN_ID,
            tool_call(CREAR_TURNO, CREAR_TURNO_ARGS),
        )
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.FORBIDDEN
    transport.assert_not_called()
    capability_spy.assert_not_called()
    audit_spy.assert_called_once()
    assert audit_spy.call_args.args[0].allowed is False


def test_tool_outside_intersection_is_forbidden_without_calling_client(
    capability_spy: CapabilitySpy,
    audit_spy: Mock,
) -> None:
    transport = TransportSpy()
    resolver = ResolverSpy(
        allowed_tools=CATALOG | {CREAR_TURNO},
        endpoint=ALLOWED_MCP_ENDPOINT,
    )
    executor = _make_executor(
        capability_spy,
        resolver,
        audit_spy,
        transport=transport,
        allowed_hosts=(ALLOWED_MCP_HOST,),
        server_tools=CATALOG | {CREAR_TURNO},
        tenant_tools=TENANT_A_TOOLS,
        skill_tools=CATALOG | {CREAR_TURNO},
    )

    result = _run(
        executor.execute(
            TENANT_A_CTX,
            RUN_ID,
            tool_call(CREAR_TURNO, CREAR_TURNO_ARGS),
        )
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.FORBIDDEN
    transport.assert_not_called()
    capability_spy.assert_not_called()
    resolver.assert_not_called()


def test_transport_without_allowed_hosts_cannot_build(
    capability_spy: CapabilitySpy,
    resolver_spy: ResolverSpy,
) -> None:
    transport = TransportSpy()
    with pytest.raises(ValueError) as caught:
        ToolExecutor(
            server=CATALOG | {CREAR_TURNO},
            tenant=CATALOG | {CREAR_TURNO},
            skill=CATALOG | {CREAR_TURNO},
            capability=capability_spy,
            resolver=resolver_spy,
            transport=transport,
        )
    assert "allowed_hosts" in str(caught.value)
    transport.assert_not_called()


def test_transport_without_resolver_cannot_build(
    capability_spy: CapabilitySpy,
) -> None:
    with pytest.raises(ValueError) as caught:
        ToolExecutor(
            server=CATALOG | {CREAR_TURNO},
            tenant=CATALOG | {CREAR_TURNO},
            skill=CATALOG | {CREAR_TURNO},
            capability=capability_spy,
            allowed_hosts=(ALLOWED_MCP_HOST,),
            transport=TransportSpy(),
        )
    message = str(caught.value)
    assert "resolver" in message
    assert "transport" in message or "allowed_hosts" in message
