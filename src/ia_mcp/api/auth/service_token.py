"""Per-request authentication of the administrative plane (ADR-007).

A caller presents `Authorization: Bearer <token>`. Each administrative
principal the deployment declared owns one token, stored as an `sm://`
reference and resolved through `SecretResolver`; the presented token is
compared against every declared token in constant time and the matching
binding's `Principal` — its roles and, when it has one, its tenant — becomes
the request's identity. No token value is ever written to this process's
configuration, only its reference.

The roster is one variable, `IA_MCP_ADMIN_PRINCIPALS`, holding entries
separated by `,`; each entry is `name=value` fields separated by `;`:

    principal=<uuid>;roles=<role>[|<role>…];secret=sm://…
        [;tenant_id=<uuid>;tenant_slug=<slug>]

`tenant_id` and `tenant_slug` come as a pair and bind the principal to one
tenant, which is what `tenant_admin`, `operator` and `auditor` need; a
`platform_admin` is declared without them. A malformed entry raises instead of
binding fewer principals, so a typo closes the plane rather than quietly
demoting an operator, and the failure never echoes the offending text because
it may hold a pasted credential.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from secrets import compare_digest
from typing import Protocol, runtime_checkable
from uuid import UUID

from ia_mcp.configuration.secrets import (
    SECRET_SCHEME,
    SecretResolutionError,
    SecretResolver,
)
from ia_mcp.onboarding.commands import Principal

ADMIN_PRINCIPALS = "IA_MCP_ADMIN_PRINCIPALS"
BEARER_SCHEME = "bearer"
# The roles the platform authorizes on today; a name outside this set is a typo
# or an invented privilege, and either way the roster must not accept it.
ADMIN_ROLES = frozenset({"platform_admin", "tenant_admin", "operator", "auditor"})
_ENTRY_SEPARATOR = ","
_FIELD_SEPARATOR = ";"
_ROLE_SEPARATOR = "|"
_REQUIRED_FIELDS = frozenset({"principal", "roles", "secret"})
_TENANT_FIELDS = ("tenant_id", "tenant_slug")
_ALLOWED_FIELDS = _REQUIRED_FIELDS | frozenset(_TENANT_FIELDS)
# The shape a tenant package declares, so a roster cannot invent another one.
_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# The value may carry a credential someone pasted where a reference belongs, so
# every refusal describes the shape and never repeats what was read.
_MALFORMED = (
    f"{ADMIN_PRINCIPALS} entries must be "
    "principal=<uuid>;roles=<role>[|<role>];secret=sm://<path>"
    "[;tenant_id=<uuid>;tenant_slug=<slug>]"
)


@runtime_checkable
class AdminAuthenticator(Protocol):
    """Turns presented credentials into an administrative identity."""

    async def authenticate(self, credentials: str | None) -> Principal | None: ...


@dataclass(frozen=True, slots=True)
class PrincipalBinding:
    """One declared principal and the reference naming its token."""

    principal: Principal
    token_reference: str


class ServiceTokenAuthenticator:
    """Authenticates a bearer token against the declared service tokens."""

    def __init__(
        self, bindings: Iterable[PrincipalBinding], secrets: SecretResolver
    ) -> None:
        self._bindings = tuple(bindings)
        self._secrets = secrets

    async def authenticate(self, credentials: str | None) -> Principal | None:
        presented = _bearer_token(credentials)
        if presented is None:
            return None
        digest = _digest(presented)
        matched: Principal | None = None
        for binding in self._bindings:
            expected = await self._expected_digest(binding)
            # Every binding is compared and none breaks the loop: an early exit
            # would make the work depend on which token was presented.
            if expected is not None and compare_digest(digest, expected):
                matched = binding.principal if matched is None else matched
        return matched

    async def _expected_digest(self, binding: PrincipalBinding) -> bytes | None:
        """Digest of a declared token, or nothing when it does not resolve.

        A binding the deployment cannot resolve authenticates nobody and does
        not disturb the others: an operator error must not open the plane, and
        it must not close a correctly configured principal either.
        """
        try:
            token = await self._secrets.resolve(binding.token_reference)
        except SecretResolutionError:
            return None
        return _digest(token.get_secret_value())


def admin_bindings_from(environ: Mapping[str, str]) -> tuple[PrincipalBinding, ...]:
    """Parse the declared roster, or refuse it."""
    bindings: list[PrincipalBinding] = []
    for entry in environ.get(ADMIN_PRINCIPALS, "").split(_ENTRY_SEPARATOR):
        item = entry.strip()
        if item:
            bindings.append(_binding(item))
    return tuple(bindings)


def _binding(entry: str) -> PrincipalBinding:
    fields = _fields(entry)
    reference = fields["secret"]
    if not reference.startswith(SECRET_SCHEME):
        raise ValueError(_MALFORMED)
    return PrincipalBinding(
        principal=Principal(
            principal_id=_uuid(fields["principal"]),
            roles=_roles(fields["roles"]),
            tenant_id=_tenant_id(fields),
            tenant_slug=_tenant_slug(fields),
        ),
        token_reference=reference,
    )


def _fields(entry: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw in entry.split(_FIELD_SEPARATOR):
        name, separator, value = raw.partition("=")
        key = name.strip()
        if not separator or key in fields:
            raise ValueError(_MALFORMED)
        fields[key] = value.strip()
    if not _REQUIRED_FIELDS <= set(fields) or not set(fields) <= _ALLOWED_FIELDS:
        raise ValueError(_MALFORMED)
    present = [name for name in _TENANT_FIELDS if fields.get(name)]
    if present and len(present) != len(_TENANT_FIELDS):
        raise ValueError(_MALFORMED)
    return fields


def _roles(value: str) -> frozenset[str]:
    roles = frozenset(item.strip() for item in value.split(_ROLE_SEPARATOR))
    if not roles or not roles <= ADMIN_ROLES:
        raise ValueError(_MALFORMED)
    return roles


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError(_MALFORMED) from exc


def _tenant_id(fields: Mapping[str, str]) -> UUID | None:
    value = fields.get(_TENANT_FIELDS[0], "")
    return _uuid(value) if value else None


def _tenant_slug(fields: Mapping[str, str]) -> str | None:
    value = fields.get(_TENANT_FIELDS[1], "")
    if not value:
        return None
    if _SLUG_RE.fullmatch(value) is None:
        raise ValueError(_MALFORMED)
    return value


def _bearer_token(credentials: str | None) -> str | None:
    if credentials is None:
        return None
    scheme, separator, token = credentials.partition(" ")
    if not separator or scheme.lower() != BEARER_SCHEME:
        return None
    return token.strip() or None


def _digest(value: str) -> bytes:
    """Fixed-width digest so a comparison cannot leak a token's length."""
    return hashlib.sha256(value.encode("utf-8")).digest()
