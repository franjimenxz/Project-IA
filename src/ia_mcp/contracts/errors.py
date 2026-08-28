from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ToolErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    CONTRACT_VIOLATION = "contract_violation"
    TENANT_ISOLATION_VIOLATION = "tenant_isolation_violation"


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ToolErrorCode
    retryable: bool
    safe_message: str
    upstream_reference: str | None = None
