"""In-process FastMCP-style SSE peer. No LAN hosts required."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

CallErrorMode = Literal["rpc", "is_error", "malformed"] | None


class FakeSseMcpServer:
    def __init__(self) -> None:
        self.call_error: CallErrorMode = None
        self.call_delay_seconds = 0.0
        self.sessions: dict[str, dict[str, Any]] = {}
        self.post_session_ids: list[str] = []
        self.http_gets = 0
        self.http_posts = 0
        self._closed = threading.Event()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._closed.set()
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)


def _handler_for(server: FakeSseMcpServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            server.http_gets += 1
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
            try:
                while not server._closed.wait(0.05):
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
            server.http_posts += 1
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
        if server.call_delay_seconds:
            time.sleep(server.call_delay_seconds)
        if server.call_error == "malformed":
            return json.dumps({"foo": True, "not": "jsonrpc"})
        if server.call_error == "rpc":
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {"code": -32602, "message": "invalid params"},
                }
            )
        if server.call_error == "is_error":
            return json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {
                        "content": [{"type": "text", "text": "tool failed"}],
                        "isError": True,
                    },
                }
            )
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
