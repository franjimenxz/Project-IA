"""SseMcpClient against an in-process FastMCP-style SSE fake.

Deviation: pytest-asyncio is not installed and must not be added; tests wrap
coroutines with asyncio.run.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Coroutine, Iterable
from pathlib import Path
from typing import Any, get_type_hints
from uuid import uuid4

import pytest

from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp.client import SseMcpClient
from ia_mcp.mcp.discovery import DiscoveredToolCatalog
from ia_mcp.mcp.executor import HostAllowlist, McpTarget
from ia_mcp.shared.errors import DomainError
from ia_mcp.tenancy.models import TenantContext
from tests.unit.mcp.fakes.sse_server import FakeSseMcpServer

TOOL_NAMES = frozenset({"crear_turno", "buscar_eventos"})
SECRET_AUTH_REFERENCE = "sk-live-mcp-secret-do-not-leak"
_CONTRACT_OR_VALIDATION = {
    ToolErrorCode.CONTRACT_VIOLATION,
    ToolErrorCode.VALIDATION_ERROR,
}

TENANT_A = TenantContext(
    tenant_id=uuid4(),
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=uuid4(),
)
TENANT_B = TenantContext(
    tenant_id=uuid4(),
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=uuid4(),
)


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _client(hosts: Iterable[str] = ("http://127.0.0.1",)) -> SseMcpClient:
    return SseMcpClient(allowlist=HostAllowlist(hosts))


def _target(
    fake_server: FakeSseMcpServer,
    *,
    allowed_tools: frozenset[str] = TOOL_NAMES,
) -> McpTarget:
    return McpTarget(
        server_id="fake-mcp",
        endpoint=fake_server.url,
        auth_reference=SECRET_AUTH_REFERENCE,
        allowed_tools=allowed_tools,
    )


@pytest.fixture()
def fake_server() -> FakeSseMcpServer:
    server = FakeSseMcpServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def target(fake_server: FakeSseMcpServer) -> McpTarget:
    return _target(fake_server)


def test_list_tools_discovers_crear_turno_and_buscar_eventos(
    target: McpTarget,
) -> None:
    catalog = _run(_client().list_tools(TENANT_A, target))
    assert isinstance(catalog, DiscoveredToolCatalog)
    assert catalog.server_id == "fake-mcp"
    assert catalog.names() == TOOL_NAMES
    assert {tool.name for tool in catalog.tools} == TOOL_NAMES


def test_list_tools_intersects_allowed_tools(target: McpTarget) -> None:
    restricted = McpTarget(
        server_id=target.server_id,
        endpoint=target.endpoint,
        auth_reference=target.auth_reference,
        allowed_tools=frozenset({"crear_turno"}),
    )
    catalog = _run(_client().list_tools(TENANT_A, restricted))
    assert catalog.names() == frozenset({"crear_turno"})
    assert all(tool.name == "crear_turno" for tool in catalog.tools)


def test_list_tools_intersect_allowed_false_keeps_all_names(target: McpTarget) -> None:
    restricted = McpTarget(
        server_id=target.server_id,
        endpoint=target.endpoint,
        auth_reference=target.auth_reference,
        allowed_tools=frozenset(),
    )
    catalog = _run(
        _client().list_tools(TENANT_A, restricted, intersect_allowed=False)
    )
    assert catalog.names() == TOOL_NAMES


def test_client_does_not_invent_authorization_headers() -> None:
    source = Path("src/ia_mcp/mcp/client.py").read_text(encoding="utf-8")
    assert "Authorization" not in source
    assert "Bearer " not in source


def test_call_tool_happy_path_returns_tool_result(target: McpTarget) -> None:
    result = _run(
        _client().call_tool(
            TENANT_A,
            target,
            "crear_turno",
            {"slot": "2026-09-01T10:00"},
        )
    )
    assert result.ok is True
    assert result.value is not None
    payload = result.value
    if isinstance(payload, dict) and "arguments" in payload:
        assert payload["arguments"]["slot"] == "2026-09-01T10:00"
    else:
        assert "2026-09-01T10:00" in json.dumps(payload)


def test_public_methods_require_tenant_context() -> None:
    hints_list = get_type_hints(SseMcpClient.list_tools)
    hints_call = get_type_hints(SseMcpClient.call_tool)
    assert hints_list["tenant"] is TenantContext
    assert hints_list["target"] is McpTarget
    assert hints_list["return"] is DiscoveredToolCatalog
    assert hints_call["tenant"] is TenantContext
    assert hints_call["target"] is McpTarget
    list_params = inspect.signature(SseMcpClient.list_tools).parameters
    call_params = inspect.signature(SseMcpClient.call_tool).parameters
    assert tuple(list_params)[1] == "tenant"
    assert tuple(call_params)[1] == "tenant"
    client = _client()
    endpoint = McpTarget(
        server_id="x",
        endpoint="http://127.0.0.1:9",
        allowed_tools=TOOL_NAMES,
    )
    with pytest.raises(TypeError):
        _run(client.list_tools(target=endpoint))
    with pytest.raises(TypeError):
        _run(client.call_tool(target=endpoint, name="crear_turno", arguments={}))


def test_tenants_do_not_share_session_state(
    fake_server: FakeSseMcpServer,
    target: McpTarget,
) -> None:
    client = _client()
    created = _run(
        client.call_tool(TENANT_A, target, "crear_turno", {"slot": "tenant-a-only"})
    )
    assert created.ok is True
    seen_by_a = _run(client.call_tool(TENANT_A, target, "buscar_eventos", {}))
    seen_by_b = _run(client.call_tool(TENANT_B, target, "buscar_eventos", {}))
    assert seen_by_a.ok is True
    assert seen_by_b.ok is True
    events_a = _events(seen_by_a.value)
    events_b = _events(seen_by_b.value)
    assert any(event.get("slot") == "tenant-a-only" for event in events_a)
    assert events_b == []
    assert len(set(fake_server.post_session_ids)) >= 2


def test_concurrent_calls_on_same_session_both_succeed(
    fake_server: FakeSseMcpServer,
    target: McpTarget,
) -> None:
    fake_server.call_delay_seconds = 0.1
    fake_server.reverse_call_responses = True
    client = _client()

    async def _both() -> tuple[object, object]:
        return await asyncio.gather(
            client.call_tool(TENANT_A, target, "crear_turno", {"slot": "one"}),
            client.call_tool(TENANT_A, target, "crear_turno", {"slot": "two"}),
        )

    first, second = _run(_both())
    assert first.ok is True
    assert second.ok is True
    assert _slot(first.value) == "one"
    assert _slot(second.value) == "two"


def test_notification_mid_call_does_not_fail_tools_call(
    fake_server: FakeSseMcpServer,
    target: McpTarget,
) -> None:
    fake_server.notify_before_call = {
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": {"progress": 0.5},
    }
    result = _run(
        _client().call_tool(TENANT_A, target, "crear_turno", {"slot": "after-notify"})
    )
    assert result.ok is True
    assert _slot(result.value) == "after-notify"


def test_jsonrpc_error_object_is_not_ok(fake_server: FakeSseMcpServer) -> None:
    fake_server.call_error = "rpc"
    result = _run(
        _client().call_tool(TENANT_A, _target(fake_server), "crear_turno", {"slot": "x"})
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.VALIDATION_ERROR


def test_tool_is_error_result_is_not_ok(fake_server: FakeSseMcpServer) -> None:
    fake_server.call_error = "is_error"
    result = _run(
        _client().call_tool(TENANT_A, _target(fake_server), "crear_turno", {"slot": "x"})
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code is ToolErrorCode.CONTRACT_VIOLATION


def test_malformed_jsonrpc_maps_to_contract_or_validation_error(
    fake_server: FakeSseMcpServer,
    target: McpTarget,
) -> None:
    fake_server.call_error = "malformed"
    result = _run(_client().call_tool(TENANT_A, target, "crear_turno", {"slot": "x"}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code in _CONTRACT_OR_VALIDATION


def test_auth_reference_is_absent_from_error_surfaces(
    fake_server: FakeSseMcpServer,
    target: McpTarget,
) -> None:
    fake_server.call_error = "malformed"
    result = _run(_client().call_tool(TENANT_A, target, "crear_turno", {"slot": "x"}))
    assert result.ok is False
    assert result.error is not None
    blob = result.model_dump_json() + result.error.safe_message
    assert SECRET_AUTH_REFERENCE not in blob


def test_host_not_allowlisted_makes_no_request(
    fake_server: FakeSseMcpServer,
) -> None:
    target = _target(fake_server)
    client = _client(hosts=("example.com",))
    with pytest.raises(DomainError) as caught:
        _run(client.list_tools(TENANT_A, target))
    assert caught.value.code == ToolErrorCode.FORBIDDEN.value
    assert "_ClientError" not in type(caught.value).__name__
    assert fake_server.http_gets == 0
    assert fake_server.http_posts == 0


def test_http_loopback_works_when_host_is_listed(
    fake_server: FakeSseMcpServer,
) -> None:
    target = _target(fake_server)
    catalog = _run(_client(hosts=("http://127.0.0.1",)).list_tools(TENANT_A, target))
    assert catalog.names() == TOOL_NAMES
    assert fake_server.http_gets >= 1


def test_list_tools_failure_is_public_domain_error(
    fake_server: FakeSseMcpServer,
) -> None:
    target = McpTarget(
        server_id="fake-mcp",
        endpoint="http://127.0.0.1:1",
        auth_reference=SECRET_AUTH_REFERENCE,
        allowed_tools=TOOL_NAMES,
    )
    with pytest.raises(DomainError) as caught:
        _run(_client().list_tools(TENANT_A, target))
    assert caught.value.code in {
        ToolErrorCode.UPSTREAM_UNAVAILABLE.value,
        ToolErrorCode.UPSTREAM_TIMEOUT.value,
    }
    assert SECRET_AUTH_REFERENCE not in caught.value.safe_message
    assert SECRET_AUTH_REFERENCE not in str(caught.value)
    assert type(caught.value) is DomainError


def _slot(value: object) -> str:
    if isinstance(value, dict):
        arguments = value.get("arguments")
        if isinstance(arguments, dict) and arguments.get("slot") is not None:
            return str(arguments["slot"])
    raise AssertionError(f"missing slot in {value!r}")


def _events(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw = value.get("events", value)
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    return []
