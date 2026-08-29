"""Administrative identities for suites that must present a real token.

Every suite that used to publish `app.state.principal` now presents an
`Authorization` header instead, so the request travels the same path a
deployment does: header, bearer scheme, constant-time comparison against a
reference resolved by a `SecretResolver`. The authenticator built here is the
production `ServiceTokenAuthenticator`; only the secret store is in memory, so
no test can pass by skipping the verification.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import SecretStr

from ia_mcp.api.auth.service_token import PrincipalBinding, ServiceTokenAuthenticator
from ia_mcp.configuration.secrets import SecretResolutionError
from ia_mcp.onboarding.commands import Principal

REFERENCE_PREFIX = "sm://test/admin-token-"


class InMemorySecrets:
    """Resolves the references this fixture minted, and nothing else."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    async def resolve(self, reference: str) -> SecretStr:
        value = self._values.get(reference)
        if value is None:
            raise SecretResolutionError(reference)
        return SecretStr(value)


def admin_authenticator(tokens: Mapping[str, Principal]) -> ServiceTokenAuthenticator:
    """Build an authenticator that maps each token to its principal."""
    bindings: list[PrincipalBinding] = []
    values: dict[str, str] = {}
    for index, (token, principal) in enumerate(tokens.items()):
        reference = f"{REFERENCE_PREFIX}{index}"
        values[reference] = token
        bindings.append(
            PrincipalBinding(principal=principal, token_reference=reference)
        )
    return ServiceTokenAuthenticator(bindings, InMemorySecrets(values))


def bearer(token: str) -> dict[str, str]:
    """The header an administrative caller presents."""
    return {"Authorization": f"Bearer {token}"}
