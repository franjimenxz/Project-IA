from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp.executor import ToolAuditEvent

_SENSITIVE = ("token", "secret", "password", "credential")


def _is_sensitive(value: object) -> bool:
    return any(fragment in str(value).lower() for fragment in _SENSITIVE)


def sanitize_summary(payload: Mapping[str, object] | None) -> dict[str, object]:
    if not payload:
        return {}
    cleaned: dict[str, object] = {}
    for key, value in payload.items():
        if _is_sensitive(key) or _is_sensitive(value):
            continue
        if isinstance(value, Mapping):
            cleaned[str(key)] = sanitize_summary(value)
            continue
        cleaned[str(key)] = value
    return cleaned


@dataclass(frozen=True, slots=True)
class ToolExecution:
    run_id: UUID
    tenant_id: UUID
    tool: str
    allowed: bool
    error_code: ToolErrorCode | None = None
    mcp_server_id: str | None = None
    summary: Mapping[str, object] | None = None


@dataclass
class ToolAuditAdapter:
    executions: list[ToolExecution] = field(default_factory=list)

    def __call__(self, event: ToolAuditEvent) -> None:
        raw: dict[str, object] = {
            "tool": event.tool,
            "allowed": event.allowed,
        }
        if event.error_code is not None:
            raw["error_code"] = event.error_code.value
        if event.mcp_server_id is not None:
            raw["mcp_server_id"] = event.mcp_server_id
        self.executions.append(
            ToolExecution(
                run_id=event.run_id,
                tenant_id=event.tenant_id,
                tool=event.tool,
                allowed=event.allowed,
                error_code=event.error_code,
                mcp_server_id=event.mcp_server_id,
                summary=sanitize_summary(raw),
            )
        )
