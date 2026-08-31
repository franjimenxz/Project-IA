"""Lab MCP endpoint map (AC-P15-002, AC-P15-003).

No network: URL validation and the JSON map are local. Secrets and userinfo
must not be persisted.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ia_mcp.onboarding.lab_mcp import (
    LAB_ENDPOINTS_FILE,
    SseLabMcpDiscoverer,
    allowlist_entry_for,
    load_lab_mcp_endpoints,
    validate_lab_mcp_endpoint,
    write_lab_mcp_endpoint,
)

LAN_SSE = "http://192.168.1.247:8001/sse"
HTTPS_SSE = "https://mcp.example.com/sse"


def test_validate_accepts_lan_http_sse() -> None:
    assert validate_lab_mcp_endpoint(LAN_SSE) == LAN_SSE
    assert validate_lab_mcp_endpoint(f"  {LAN_SSE}  ") == LAN_SSE


def test_validate_rejects_userinfo() -> None:
    with pytest.raises(ValueError):
        validate_lab_mcp_endpoint("http://user:secret@192.168.1.247:8001/sse")


def test_validate_rejects_file_scheme() -> None:
    with pytest.raises(ValueError):
        validate_lab_mcp_endpoint("file:///tmp/mcp")


def test_validate_rejects_link_local_metadata_host() -> None:
    with pytest.raises(ValueError):
        validate_lab_mcp_endpoint("https://169.254.169.254/latest/meta-data/")


def test_allowlist_entry_keeps_http_scheme_and_bare_https_host() -> None:
    assert allowlist_entry_for(LAN_SSE) == "http://192.168.1.247"
    assert allowlist_entry_for(HTTPS_SSE) == "mcp.example.com"


def test_write_and_load_roundtrip_without_secrets(tmp_path: Path) -> None:
    path = write_lab_mcp_endpoint(tmp_path, "soloturnos", LAN_SSE)
    assert path == tmp_path / LAB_ENDPOINTS_FILE
    assert load_lab_mcp_endpoints(tmp_path) == {"soloturnos": LAN_SSE}
    blob = path.read_text(encoding="utf-8")
    payload = json.loads(blob)
    assert payload == {"soloturnos": LAN_SSE}
    assert "secret" not in blob.lower()
    assert "api_key" not in blob
    assert "password" not in blob
    assert "user:" not in blob


def test_write_merges_existing_map(tmp_path: Path) -> None:
    write_lab_mcp_endpoint(tmp_path, "soloturnos", LAN_SSE)
    write_lab_mcp_endpoint(tmp_path, "otra", HTTPS_SSE)
    assert load_lab_mcp_endpoints(tmp_path) == {
        "soloturnos": LAN_SSE,
        "otra": HTTPS_SSE,
    }


def test_write_rejects_userinfo_and_does_not_create_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_lab_mcp_endpoint(
            tmp_path,
            "soloturnos",
            "http://user:secret@192.168.1.247:8001/sse",
        )
    assert not (tmp_path / LAB_ENDPOINTS_FILE).exists()


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_lab_mcp_endpoints(tmp_path) == {}


def test_sse_discoverer_returns_empty_without_intersect_flag() -> None:
    names = asyncio.run(SseLabMcpDiscoverer().list_names(LAN_SSE))
    assert names == ()
