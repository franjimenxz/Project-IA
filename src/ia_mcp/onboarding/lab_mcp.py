"""Lab MCP endpoint map (ADR-011).

The package schema has no `endpoint` field. The operator URL lives next to
tenant packages as `{root}/lab_mcp_endpoints.json`, keyed by `mcp_server_id`.
Values are http(s) URLs without userinfo. Secrets are never stored here.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

LAB_ENDPOINTS_FILE = "lab_mcp_endpoints.json"
_METADATA_HOST = "169.254.169.254"


class LabMcpDiscoverer(Protocol):
    async def list_names(self, endpoint: str) -> tuple[str, ...]: ...


def validate_lab_mcp_endpoint(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("mcp_endpoint must be an http(s) URL")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("mcp_endpoint must be an http(s) URL")
    if (
        parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
    ):
        raise ValueError("mcp_endpoint must not include userinfo")
    host = parsed.hostname
    if host is None or not host.strip():
        raise ValueError("mcp_endpoint must include a host")
    lowered = host.lower()
    if lowered == _METADATA_HOST or _is_link_local(lowered):
        raise ValueError("mcp_endpoint host is not allowed")
    return raw


def allowlist_entry_for(endpoint: str) -> str:
    """ADR-005: https → hostname; http → `http://hostname`."""
    parsed = urlsplit(validate_lab_mcp_endpoint(endpoint))
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https":
        return host
    return f"http://{host}"


def load_lab_mcp_endpoints(root: Path) -> dict[str, str]:
    path = root / LAB_ENDPOINTS_FILE
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    loaded: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, str):
            continue
        try:
            loaded[key.strip()] = validate_lab_mcp_endpoint(value)
        except ValueError:
            continue
    return loaded


def write_lab_mcp_endpoint(root: Path, server_id: str, endpoint: str) -> Path:
    name = server_id.strip()
    if not name:
        raise ValueError("server_id is required")
    validated = validate_lab_mcp_endpoint(endpoint)
    current = load_lab_mcp_endpoints(root)
    current[name] = validated
    path = root / LAB_ENDPOINTS_FILE
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return path


class SseLabMcpDiscoverer:
    """Production discoverer until T03 adds `intersect_allowed=False`.

    `SseMcpClient.list_tools` currently drops names when `allowed_tools` is
    empty, so this adapter returns `()` and does not open a network socket.
    Tests inject `app.state.lab_mcp_discoverer`.
    """

    async def list_names(self, endpoint: str) -> tuple[str, ...]:
        del endpoint
        return ()


def _is_link_local(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_link_local
    except ValueError:
        return False
