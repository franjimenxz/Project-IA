"""Secret resolution port.

Tenant configuration stores `credentials_reference`/`secret_reference` values
as `sm://` references and never the credential itself (RF-037, ADR-007). This
module owns the port that turns one reference into its value, and the typed
failure a caller gets when it cannot.

Two properties are load-bearing:

- **Fail closed.** An unknown, malformed or unset reference raises
  `SecretResolutionError`. No adapter may substitute a default, an empty string
  or a neighbouring reference.
- **The value never leaves as text.** Resolution returns `SecretStr`, whose
  `str`/`repr` render a mask, so a value that reaches a log line, a span
  attribute or an f-string is masked instead of printed. Only
  `get_secret_value()` yields the credential, and only a transport or a
  comparison should call it.

The port is deliberately not tenant-scoped: a reference is an opaque
identifier, and ownership is decided by the tenant-scoped query that produced
it (preflight reads references from the tenant's own rows; the admin
authenticator reads them from deployment configuration). No caller may hand
this port a reference that arrived from a request.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import SecretStr

from ia_mcp.shared.errors import DomainError

SECRET_SCHEME = "sm://"


class SecretResolutionError(DomainError):
    """A reference that could not be turned into a value.

    `safe_message` is generic and `details` carries the reference only: the
    reference names a secret and is not one, while the value is never placed on
    the exception at all, so logging or serializing it cannot leak a
    credential.
    """

    def __init__(self, reference: str, *, code: str = "secret_unresolved") -> None:
        super().__init__(
            code=code,
            safe_message="Secret reference could not be resolved.",
            retryable=False,
            details={"reference": reference},
        )


class SecretResolver(Protocol):
    """Resolves one `sm://` reference to its value, or fails closed."""

    async def resolve(self, reference: str) -> SecretStr: ...
