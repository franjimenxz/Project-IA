"""Optional live FastMCP SSE check. Skipped unless MCP_SSE_URL is set."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from ia_mcp.mcp.client import SseMcpClient
from ia_mcp.mcp.executor import HostAllowlist, McpTarget
from ia_mcp.tenancy.models import TenantContext

MCP_SSE_URL = os.environ.get("MCP_SSE_URL", "").strip()

pytestmark = pytest.mark.e2e


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _live_allowlist(url: str) -> HostAllowlist:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    scheme = parsed.scheme or "http"
    return HostAllowlist((f"{scheme}://{host}", host))


@pytest.mark.skipif(not MCP_SSE_URL, reason="MCP_SSE_URL is not set")
def test_live_sse_lists_tools() -> None:
    tenant = TenantContext(
        tenant_id=uuid4(),
        tenant_slug="live-probe",
        config_version=1,
        correlation_id=uuid4(),
    )
    target = McpTarget(
        server_id="live-mcp",
        endpoint=MCP_SSE_URL,
        allowed_tools=frozenset(),
    )
    # Live catalog is unknown; empty allowlist yields an empty intersection
    # after a successful tools/list. Probe only that discovery returns.
    catalog = _run(
        SseMcpClient(
            allowlist=_live_allowlist(MCP_SSE_URL), timeout_seconds=15.0
        ).list_tools(tenant, target)
    )
    assert catalog.server_id == "live-mcp"
    assert catalog.names() == frozenset()
