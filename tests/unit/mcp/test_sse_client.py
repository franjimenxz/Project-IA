"""SseMcpClient against an in-process FastMCP-style SSE fake.

Deviation: pytest-asyncio is not installed and must not be added; tests wrap
coroutines with asyncio.run.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
from collections.abc import Coroutine, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, get_type_hints
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp.client import SseMcpClient
from ia_mcp.mcp.discovery import McpEndpoint
from ia_mcp.tenancy.models import TenantContext

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


class FakeSseMcpServer:
    """Minimal GET /sse + POST /messages/?session_id= peer for unit tests."""

    def __init__(self) -> None:
        self.malformed_rpc = False
        self.sessions: dict[str, dict[str, Any]] = {}
        self.post_session_ids: list[str] = []
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)


def _handler_for(server: FakeSseMcpServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/sse":
                self.send_error(404)
                return
            session_id = uuid4().hex
            bucket: dict[str, Any] = {
                "events": [],
                "outbound": [],
                "ready": threading.Event(),
                "lock": threading.Lock(),
            }
            server.sessions[session_id] = bucket
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            payload = f"event: endpoint\ndata: /messages/?session_id={session_id}\n\n"
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
            bucket["ready"].set()
            deadline = threading.Event()
            try:
                while not deadline.wait(0.05):
                    with bucket["lock"]:
                        pending = list(bucket["outbound"])
                        bucket["outbound"].clear()
                    for message in pending:
                        frame = f"event: message\ndata: {message}\n\n"
                        self.wfile.write(frame.encode("utf-8"))
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.rstrip("/") != "/messages":
                self.send_error(404)
                return
            session_id = (parse_qs(parsed.query).get("session_id") or [""])[0]
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            server.post_session_ids.append(session_id)
            session = server.sessions.get(session_id)
            if session is None:
                self.send_error(404)
                return
            session["ready"].wait(timeout=1)
            try:
                request = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                request = {}
            response = _rpc_response(server, session, request)
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            if response is not None:
                with session["lock"]:
                    session["outbound"].append(response)

    return Handler


def _rpc_response(
    server: FakeSseMcpServer,
    session: dict[str, Any],
    request: Mapping[str, Any],
) -> str | None:
    method = request.get("method")
    rpc_id = request.get("id")
    if method == "notifications/initialized":
        return None
    if server.malformed_rpc and method == "tools/call":
        return json.dumps({"foo": True, "not": "jsonrpc"})
    if method == "initialize":
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "0.0.0"},
                },
            }
        )
    if method == "tools/list":
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "tools": [
                        {
                            "name": "crear_turno",
                            "description": "Create an appointment slot",
                            "inputSchema": {"type": "object"},
                        },
                        {
                            "name": "buscar_eventos",
                            "description": "Search stored events",
                            "inputSchema": {"type": "object"},
                        },
                    ]
                },
            }
        )
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "crear_turno":
            session["events"].append(dict(arguments))
            value: dict[str, Any] = {"created": True, "arguments": dict(arguments)}
        elif name == "buscar_eventos":
            value = {"events": list(session["events"])}
        else:
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32601, "message": "Unknown tool"},
                }
            )
        return json.dumps(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(value)}],
                    "structuredContent": value,
                    "isError": False,
                },
            }
        )
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": "Method not found"},
        }
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
def target(fake_server: FakeSseMcpServer) -> McpEndpoint:
    return McpEndpoint(
        server_id="fake-mcp",
        endpoint=fake_server.url,
        auth_reference=SECRET_AUTH_REFERENCE,
    )


def test_list_tools_discovers_crear_turno_and_buscar_eventos(
    target: McpEndpoint,
) -> None:
    client = SseMcpClient()
    catalog = _run(client.list_tools(TENANT_A, target))
    assert catalog.names() == TOOL_NAMES
    discovered = {tool.name for tool in catalog.tools()}
    assert discovered == TOOL_NAMES


def test_call_tool_happy_path_returns_tool_result(target: McpEndpoint) -> None:
    client = SseMcpClient()
    result = _run(
        client.call_tool(
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
    assert hints_call["tenant"] is TenantContext
    list_params = inspect.signature(SseMcpClient.list_tools).parameters
    call_params = inspect.signature(SseMcpClient.call_tool).parameters
    assert tuple(list_params)[1] == "tenant"
    assert tuple(call_params)[1] == "tenant"
    client = SseMcpClient()
    endpoint = McpEndpoint(server_id="x", endpoint="http://127.0.0.1:9")
    with pytest.raises(TypeError):
        _run(client.list_tools(target=endpoint))
    with pytest.raises(TypeError):
        _run(client.call_tool(target=endpoint, name="crear_turno", arguments={}))


def test_tenants_do_not_share_session_state(
    fake_server: FakeSseMcpServer,
    target: McpEndpoint,
) -> None:
    client = SseMcpClient()
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


def test_malformed_jsonrpc_maps_to_contract_or_validation_error(
    fake_server: FakeSseMcpServer,
    target: McpEndpoint,
) -> None:
    fake_server.malformed_rpc = True
    client = SseMcpClient()
    result = _run(client.call_tool(TENANT_A, target, "crear_turno", {"slot": "x"}))
    assert result.ok is False
    assert result.error is not None
    assert result.error.code in _CONTRACT_OR_VALIDATION


def test_auth_reference_is_absent_from_error_surfaces(
    fake_server: FakeSseMcpServer,
    target: McpEndpoint,
) -> None:
    fake_server.malformed_rpc = True
    client = SseMcpClient()
    result = _run(client.call_tool(TENANT_A, target, "crear_turno", {"slot": "x"}))
    assert result.ok is False
    assert result.error is not None
    blob = result.model_dump_json() + result.error.safe_message
    assert SECRET_AUTH_REFERENCE not in blob


def _events(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        raw = value.get("events", value)
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
    return []
