"""Optional live FastMCP SSE check. Skipped unless MCP_SSE_URL is set."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from uuid import uuid4

import pytest

from ia_mcp.mcp.client import SseMcpClient
from ia_mcp.mcp.discovery import McpEndpoint
from ia_mcp.tenancy.models import TenantContext

MCP_SSE_URL = os.environ.get("MCP_SSE_URL", "").strip()

pytestmark = pytest.mark.e2e


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


@pytest.mark.skipif(not MCP_SSE_URL, reason="MCP_SSE_URL is not set")
def test_live_sse_lists_tools() -> None:
    tenant = TenantContext(
        tenant_id=uuid4(),
        tenant_slug="live-probe",
        config_version=1,
        correlation_id=uuid4(),
    )
    target = McpEndpoint(server_id="live-mcp", endpoint=MCP_SSE_URL)
    catalog = _run(SseMcpClient(timeout_seconds=15.0).list_tools(tenant, target))
    assert catalog.names()
    assert catalog.tools()
