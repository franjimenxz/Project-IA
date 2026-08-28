from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from collections.abc import Mapping
from http.client import HTTPConnection, HTTPException, HTTPResponse, HTTPSConnection
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolError, ToolErrorCode
from ia_mcp.mcp.discovery import DiscoveredTool, McpEndpoint, ToolCatalog
from ia_mcp.observability.redaction import redact
from ia_mcp.tenancy.models import TenantContext

_PROTOCOL = "2024-11-05"
_CLIENT_INFO = {"name": "ia-mcp", "version": "0.0.0"}


class SseMcpClient:
    def __init__(self, *, timeout_seconds: float = 10.0) -> None:
        self._timeout = timeout_seconds
        self._sessions: dict[tuple[UUID, str, str], _SseSession] = {}
        self._lock = threading.Lock()

    async def list_tools(
        self, tenant: TenantContext, target: McpEndpoint
    ) -> ToolCatalog:
        return await asyncio.to_thread(self._list_tools_sync, tenant, target)

    async def call_tool(
        self,
        tenant: TenantContext,
        target: McpEndpoint,
        name: str,
        arguments: Mapping[str, Any],
    ) -> ToolResult[Any]:
        return await asyncio.to_thread(
            self._call_tool_sync, tenant, target, name, arguments
        )

    def _list_tools_sync(
        self, tenant: TenantContext, target: McpEndpoint
    ) -> ToolCatalog:
        session = self._session(tenant, target)
        message = session.request("tools/list", {})
        result = _require_result(message)
        raw_tools = result.get("tools")
        if not isinstance(raw_tools, list):
            raise _ClientError(
                ToolErrorCode.CONTRACT_VIOLATION,
                _safe_text("The upstream response is not valid JSON-RPC.", target),
            )
        tools: list[DiscoveredTool] = []
        for item in raw_tools:
            if not isinstance(item, Mapping) or not item.get("name"):
                raise _ClientError(
                    ToolErrorCode.CONTRACT_VIOLATION,
                    _safe_text("The upstream response is not valid JSON-RPC.", target),
                )
            schema = item.get("inputSchema") or {}
            if not isinstance(schema, Mapping):
                schema = {}
            tools.append(
                DiscoveredTool(
                    name=str(item["name"]),
                    description=str(item.get("description") or ""),
                    input_schema=dict(schema),
                )
            )
        return ToolCatalog(tools)

    def _call_tool_sync(
        self,
        tenant: TenantContext,
        target: McpEndpoint,
        name: str,
        arguments: Mapping[str, Any],
    ) -> ToolResult[Any]:
        try:
            session = self._session(tenant, target)
            message = session.request(
                "tools/call",
                {"name": name, "arguments": dict(arguments)},
            )
        except _ClientError as exc:
            return _failure(exc.code, exc.safe_message)
        except TimeoutError:
            return _failure(
                ToolErrorCode.UPSTREAM_TIMEOUT,
                _safe_text("The MCP server timed out.", target),
            )
        except (HTTPException, OSError):
            return _failure(
                ToolErrorCode.UPSTREAM_UNAVAILABLE,
                _safe_text("The MCP server is unavailable.", target),
            )
        if "error" in message and "result" not in message:
            return _map_rpc_error(message, target)
        try:
            result = _require_result(message)
        except _ClientError as exc:
            return _failure(exc.code, exc.safe_message)
        if isinstance(result, Mapping) and result.get("isError"):
            return _failure(
                ToolErrorCode.CONTRACT_VIOLATION,
                _safe_text("The tool call failed.", target),
            )
        value: Any = result
        if isinstance(result, Mapping) and "structuredContent" in result:
            value = result["structuredContent"]
        return ToolResult[Any](ok=True, value=value)

    def _session(self, tenant: TenantContext, target: McpEndpoint) -> _SseSession:
        key = (tenant.tenant_id, target.server_id, _sse_url(target.endpoint))
        with self._lock:
            existing = self._sessions.get(key)
            if existing is not None and existing.alive:
                return existing
        session = _SseSession(
            sse_url=_sse_url(target.endpoint),
            timeout=self._timeout,
            target=target,
        )
        session.connect()
        session.handshake()
        with self._lock:
            current = self._sessions.get(key)
            if current is not None and current.alive:
                session.close()
                return current
            self._sessions[key] = session
            return session


class _ClientError(Exception):
    def __init__(self, code: ToolErrorCode, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class _SseSession:
    def __init__(self, *, sse_url: str, timeout: float, target: McpEndpoint) -> None:
        self._sse_url = sse_url
        self._timeout = timeout
        self._target = target
        self._events: queue.Queue[dict[str, str]] = queue.Queue()
        self._stop = threading.Event()
        self._alive = False
        self._messages_url = ""
        self._next_id = 1
        self._lock = threading.Lock()
        self._stream: HTTPConnection | None = None
        self._reader = threading.Thread(target=self._read_loop, daemon=True)

    @property
    def alive(self) -> bool:
        return self._alive and not self._stop.is_set()

    def connect(self) -> None:
        self._reader.start()
        event = self._wait_event("endpoint")
        self._messages_url = urljoin(self._sse_url, event["data"].strip())
        self._alive = True

    def handshake(self) -> None:
        self.request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL,
                "capabilities": {},
                "clientInfo": dict(_CLIENT_INFO),
            },
        )
        self.notify("notifications/initialized")

    def request(self, method: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        with self._lock:
            rpc_id = self._next_id
            self._next_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = dict(params)
        self._post(payload)
        return self._wait_rpc(rpc_id)

    def notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method})

    def close(self) -> None:
        self._alive = False
        self._stop.set()
        stream = self._stream
        if stream is not None:
            stream.close()

    def _post(self, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            connection, response = _http_request(
                self._messages_url,
                method="POST",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
            try:
                if response.status >= 400:
                    raise _ClientError(
                        ToolErrorCode.UPSTREAM_UNAVAILABLE,
                        _safe_text("The MCP server is unavailable.", self._target),
                    )
                response.read()
            finally:
                connection.close()
        except _ClientError:
            raise
        except TimeoutError as exc:
            raise _ClientError(
                ToolErrorCode.UPSTREAM_TIMEOUT,
                _safe_text("The MCP server timed out.", self._target),
            ) from exc
        except (HTTPException, OSError) as exc:
            raise _ClientError(
                ToolErrorCode.UPSTREAM_UNAVAILABLE,
                _safe_text("The MCP server is unavailable.", self._target),
            ) from exc

    def _wait_rpc(self, rpc_id: int) -> dict[str, Any]:
        deadline = _deadline(self._timeout)
        while True:
            remaining = deadline - _now()
            if remaining <= 0:
                raise _ClientError(
                    ToolErrorCode.UPSTREAM_TIMEOUT,
                    _safe_text("The MCP server timed out.", self._target),
                )
            event = self._wait_event("message", timeout=remaining)
            raw = event["data"]
            try:
                message = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise _ClientError(
                    ToolErrorCode.CONTRACT_VIOLATION,
                    _safe_text(
                        "The upstream response is not valid JSON-RPC.", self._target
                    ),
                ) from exc
            if not isinstance(message, dict):
                raise _ClientError(
                    ToolErrorCode.CONTRACT_VIOLATION,
                    _safe_text(
                        "The upstream response is not valid JSON-RPC.", self._target
                    ),
                )
            if message.get("id") != rpc_id:
                if not _is_jsonrpc(message):
                    raise _ClientError(
                        ToolErrorCode.CONTRACT_VIOLATION,
                        _safe_text(
                            "The upstream response is not valid JSON-RPC.",
                            self._target,
                        ),
                    )
                continue
            if not _is_jsonrpc(message):
                raise _ClientError(
                    ToolErrorCode.CONTRACT_VIOLATION,
                    _safe_text(
                        "The upstream response is not valid JSON-RPC.", self._target
                    ),
                )
            return message

    def _wait_event(self, name: str, timeout: float | None = None) -> dict[str, str]:
        remaining = self._timeout if timeout is None else timeout
        deadline = _deadline(remaining)
        while True:
            left = deadline - _now()
            if left <= 0:
                raise _ClientError(
                    ToolErrorCode.UPSTREAM_TIMEOUT,
                    _safe_text("The MCP server timed out.", self._target),
                )
            try:
                event = self._events.get(timeout=left)
            except queue.Empty:
                raise _ClientError(
                    ToolErrorCode.UPSTREAM_TIMEOUT,
                    _safe_text("The MCP server timed out.", self._target),
                ) from None
            if event["event"] == "_closed":
                raise _ClientError(
                    ToolErrorCode.UPSTREAM_UNAVAILABLE,
                    _safe_text("The MCP server is unavailable.", self._target),
                )
            if event["event"] == name:
                return event

    def _read_loop(self) -> None:
        try:
            connection, response = _http_request(
                self._sse_url,
                method="GET",
                body=None,
                headers={"Accept": "text/event-stream"},
                timeout=self._timeout,
            )
            self._stream = connection
            if response.status >= 400:
                raise OSError("sse rejected")
            event_name = "message"
            data_lines: list[str] = []
            while not self._stop.is_set():
                raw = response.readline()
                if raw == b"":
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    if data_lines:
                        self._events.put(
                            {
                                "event": event_name,
                                "data": "\n".join(data_lines),
                            }
                        )
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip() or "message"
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
        except (OSError, HTTPException, TimeoutError, UnicodeError):
            self._alive = False
            self._events.put({"event": "_closed", "data": ""})
            return
        self._alive = False
        self._events.put({"event": "_closed", "data": ""})


def _http_request(
    url: str,
    *,
    method: str,
    body: bytes | None,
    headers: Mapping[str, str],
    timeout: float,
) -> tuple[HTTPConnection, HTTPResponse]:
    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        raise OSError("invalid endpoint")
    port = parsed.port
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    connector: type[HTTPConnection]
    connector = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connector(host, port, timeout=timeout)
    connection.request(method, path, body=body, headers=dict(headers))
    return connection, connection.getresponse()


def _sse_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/sse"):
        return base
    return f"{base}/sse"


def _is_jsonrpc(message: Mapping[str, Any]) -> bool:
    if message.get("jsonrpc") != "2.0":
        return False
    return "result" in message or "error" in message


def _require_result(message: Mapping[str, Any]) -> dict[str, Any]:
    if not _is_jsonrpc(message) or "result" not in message:
        raise _ClientError(
            ToolErrorCode.CONTRACT_VIOLATION,
            "The upstream response is not valid JSON-RPC.",
        )
    result = message["result"]
    if not isinstance(result, dict):
        raise _ClientError(
            ToolErrorCode.CONTRACT_VIOLATION,
            "The upstream response is not valid JSON-RPC.",
        )
    return result


def _map_rpc_error(
    message: Mapping[str, Any], target: McpEndpoint
) -> ToolResult[Any]:
    payload = message.get("error")
    rpc_code = payload.get("code") if isinstance(payload, Mapping) else None
    if rpc_code in {-32700, -32600}:
        code = ToolErrorCode.CONTRACT_VIOLATION
    elif rpc_code == -32602:
        code = ToolErrorCode.VALIDATION_ERROR
    elif rpc_code == -32603:
        code = ToolErrorCode.UPSTREAM_UNAVAILABLE
    else:
        code = ToolErrorCode.CONTRACT_VIOLATION
    return _failure(code, _safe_text("The tool call failed.", target))


def _failure(code: ToolErrorCode, safe_message: str) -> ToolResult[Any]:
    retryable = code in {
        ToolErrorCode.UPSTREAM_TIMEOUT,
        ToolErrorCode.UPSTREAM_UNAVAILABLE,
    }
    return ToolResult[Any](
        ok=False,
        error=ToolError(code=code, retryable=retryable, safe_message=safe_message),
    )


def _safe_text(message: str, target: McpEndpoint) -> str:
    text = redact(message)
    secret = target.auth_reference
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text


def _now() -> float:
    return time.monotonic()


def _deadline(timeout: float) -> float:
    return _now() + timeout
