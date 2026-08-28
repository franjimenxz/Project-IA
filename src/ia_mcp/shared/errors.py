from collections.abc import Mapping
from typing import Any


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        safe_message: str,
        retryable: bool,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
        self.details: Mapping[str, Any] = details if details is not None else {}


class TenantIsolationViolation(DomainError):
    def __init__(self, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            code="tenant_isolation_violation",
            safe_message="Resource not found",
            retryable=False,
            details=details,
        )
