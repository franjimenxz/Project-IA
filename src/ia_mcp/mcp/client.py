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
from ia_mcp.mcp.discovery import DiscoveredTool, DiscoveredToolCatalog
from ia_mcp.mcp.executor import HostAllowlist, McpTarget
from ia_mcp.observability.redaction import redact
from ia_mcp.shared.errors import DomainError
from ia_mcp.tenancy.models import TenantContext

_PROTOCOL = "2024-11-05"
_CLIENT_INFO = {"name": "ia-mcp", "version": "0.0.0"}
_RETRYABLE = frozenset(
    {ToolErrorCode.UPSTREAM_TIMEOUT, ToolErrorCode.UPSTREAM_UNAVAILABLE}
)


class SseMcpClient:
    def __init__(
        self, *, allowlist: HostAllowlist, timeout_seconds: float = 10.0
    ) -> None:
        self._allowlist = allowlist
        self._timeout = timeout_seconds
        self._sessions: dict[tuple[UUID, str, str], _SseSession] = {}
        self._lock = threading.Lock()

    async def list_tools(
        self, tenant: TenantContext, target: McpTarget
    ) -> DiscoveredToolCatalog:
        return await asyncio.to_thread(self._list_tools_sync, tenant, target)

    async def call_tool(
        self,
        tenant: TenantContext,
        target: McpTarget,
        name: str,
        arguments: Mapping[str, Any],
    ) -> ToolResult[Any]:
        return await asyncio.to_thread(
            self._call_tool_sync, tenant, target, name, arguments
        )

    def _list_tools_sync(
        self, tenant: TenantContext, target: McpTarget
    ) -> DiscoveredToolCatalog:
        try:
            self._require_permitted(_sse_url(target.endpoint), target)
            session = self._session(tenant, target)
            message = session.request("tools/list", {})
            result = _require_result(message)
        except DomainError:
            raise
        except _ClientError as exc:
            raise _public_error(exc) from None
        raw_tools = result.get("tools")
        if not isinstance(raw_tools, list):
            raise _public_error(
                _ClientError(
                    ToolErrorCode.CONTRACT_VIOLATION,
                    _safe_text("The upstream response is not valid JSON-RPC.", target),
                )
            )
        tools: list[DiscoveredTool] = []
        for item in raw_tools:
            if not isinstance(item, Mapping) or not item.get("name"):
                raise _public_error(
                    _ClientError(
                        ToolErrorCode.CONTRACT_VIOLATION,
                        _safe_text(
                            "The upstream response is not valid JSON-RPC.", target
                        ),
                    )
                )
            schema = item.get("inputSchema") or {}
            if not isinstance(schema, Mapping):
                schema = {}
            name = str(item["name"])
            if name not in target.allowed_tools:
                continue
            tools.append(
                DiscoveredTool(
                    name=name,
                    description=str(item.get("description") or ""),
                    input_schema=dict(schema),
                )
            )
        return DiscoveredToolCatalog(server_id=target.server_id, tools=tuple(tools))

    def _call_tool_sync(
        self,
        tenant: TenantContext,
        target: McpTarget,
        name: str,
        arguments: Mapping[str, Any],
    ) -> ToolResult[Any]:
        try:
            self._require_permitted(_sse_url(target.endpoint), target)
            if name not in target.allowed_tools:
                return _failure(
                    ToolErrorCode.FORBIDDEN,
                    _safe_text("Action is not allowed.", target),
                )
            session = self._session(tenant, target)
            message = session.request(
                "tools/call",
                {"name": name, "arguments": dict(arguments)},
            )
        except DomainError as exc:
            return _failure(ToolErrorCode(exc.code), exc.safe_message)
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

    def _require_permitted(self, endpoint: str, target: McpTarget) -> None:
        if self._allowlist.permits(endpoint):
            return
        raise DomainError(
            code=ToolErrorCode.FORBIDDEN.value,
            safe_message=_safe_text("Action is not allowed.", target),
            retryable=False,
        )

    def _session(self, tenant: TenantContext, target: McpTarget) -> _SseSession:
        key = (tenant.tenant_id, target.server_id, _sse_url(target.endpoint))
        with self._lock:
            existing = self._sessions.get(key)
            if existing is not None and existing.alive:
                return existing
        session = _SseSession(
            sse_url=_sse_url(target.endpoint),
            timeout=self._timeout,
            target=target,
            allowlist=self._allowlist,
        )
        try:
            session.connect()
            session.handshake()
        except _ClientError as exc:
            session.close()
            raise _public_error(exc) from None
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
    def __init__(
        self,
        *,
        sse_url: str,
        timeout: float,
        target: McpTarget,
        allowlist: HostAllowlist,
    ) -> None:
        self._sse_url = sse_url
        self._timeout = timeout
        self._target = target
        self._allowlist = allowlist
        self._events: queue.Queue[dict[str, str]] = queue.Queue()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
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
        messages_url = urljoin(self._sse_url, event["data"].strip())
        if not self._allowlist.permits(messages_url):
            raise _ClientError(
                ToolErrorCode.FORBIDDEN,
                _safe_text("Action is not allowed.", self._target),
            )
        self._messages_url = messages_url
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
        waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._lock:
            rpc_id = self._next_id
            self._next_id += 1
            self._pending[rpc_id] = waiter
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = dict(params)
        try:
            self._post(payload)
            try:
                message = waiter.get(timeout=self._timeout)
            except queue.Empty:
                raise _ClientError(
                    ToolErrorCode.UPSTREAM_TIMEOUT,
                    _safe_text("The MCP server timed out.", self._target),
                ) from None
            if message.get("_malformed") or not _is_jsonrpc(message):
                raise _ClientError(
                    ToolErrorCode.CONTRACT_VIOLATION,
                    _safe_text(
                        "The upstream response is not valid JSON-RPC.", self._target
                    ),
                )
            return message
        finally:
            with self._lock:
                self._pending.pop(rpc_id, None)

    def notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method})

    def close(self) -> None:
        self._alive = False
        self._stop.set()
        stream = self._stream
        if stream is not None:
            stream.close()

    def _post(self, payload: Mapping[str, Any]) -> None:
        if self._messages_url and not self._allowlist.permits(self._messages_url):
            raise _ClientError(
                ToolErrorCode.FORBIDDEN,
                _safe_text("Action is not allowed.", self._target),
            )
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

    def _wait_event(self, name: str, timeout: float | None = None) -> dict[str, str]:
        remaining = self._timeout if timeout is None else timeout
        deadline = time.monotonic() + remaining
        while True:
            left = deadline - time.monotonic()
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

    def _offer_message(self, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            self._broadcast({"_malformed": True})
            return
        if not isinstance(message, dict):
            self._broadcast({"_malformed": True})
            return
        if "method" in message and "result" not in message and "error" not in message:
            return
        if not _is_jsonrpc(message):
            self._broadcast({"_malformed": True})
            return
        rpc_id = message.get("id")
        with self._lock:
            waiter = self._pending.get(rpc_id) if isinstance(rpc_id, int) else None
        if waiter is not None:
            waiter.put(message)

    def _broadcast(self, payload: dict[str, Any]) -> None:
        with self._lock:
            waiters = list(self._pending.values())
        for waiter in waiters:
            waiter.put(payload)

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
                        data = "\n".join(data_lines)
                        if event_name == "message":
                            self._offer_message(data)
                        else:
                            self._events.put({"event": event_name, "data": data})
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


def _map_rpc_error(message: Mapping[str, Any], target: McpTarget) -> ToolResult[Any]:
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
    return ToolResult[Any](
        ok=False,
        error=ToolError(
            code=code, retryable=code in _RETRYABLE, safe_message=safe_message
        ),
    )


def _public_error(exc: _ClientError) -> DomainError:
    return DomainError(
        code=exc.code.value,
        safe_message=exc.safe_message,
        retryable=exc.code in _RETRYABLE,
    )


def _safe_text(message: str, target: McpTarget) -> str:
    text = redact(message)
    secret = target.auth_reference
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text
