from collections.abc import Mapping
from typing import Any

from ia_mcp.agent_runtime.models import ToolObservation
from ia_mcp.contracts.common import ToolResult
from ia_mcp.mcp.audit import sanitize_summary


def observation_from(name: str, result: ToolResult[Any]) -> ToolObservation:
    if result.ok:
        raw = result.value
        payload: Mapping[str, object] | None = raw if isinstance(raw, Mapping) else None
        return ToolObservation(name=name, ok=True, value=sanitize_summary(payload))
    error = result.error
    if error is None:
        return ToolObservation(name=name, ok=False)
    return ToolObservation(
        name=name,
        ok=False,
        error_code=error.code.value,
        safe_message=error.safe_message,
    )
