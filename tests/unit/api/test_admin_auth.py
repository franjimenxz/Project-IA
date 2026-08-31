"""Service-token authentication of the administrative plane (ADR-007).

No PostgreSQL, no process environment and no HTTP stack: the roster is parsed
from a mapping and the tokens are resolved by an in-memory `SecretResolver`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr

from ia_mcp.api.auth import service_token
from ia_mcp.api.auth.service_token import (
    ADMIN_PRINCIPALS,
    AdminAuthenticator,
    PrincipalBinding,
    ServiceTokenAuthenticator,
    admin_bindings_from,
)
from ia_mcp.configuration.secrets import SecretResolutionError

PLATFORM_ID = UUID("11111111-1111-1111-1111-111111111111")
OPERATOR_ID = UUID("22222222-2222-2222-2222-222222222222")
TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PLATFORM_REFERENCE = "sm://admin/platform"
OPERATOR_REFERENCE = "sm://admin/operator-a"
PLATFORM_TOKEN = "platform-token-canary"
OPERATOR_TOKEN = "operator-token-canary"

PLATFORM_ENTRY = f"principal={PLATFORM_ID};roles=platform_admin;secret={PLATFORM_REFERENCE}"
OPERATOR_ENTRY = (
    f"principal={OPERATOR_ID};roles=operator|auditor;secret={OPERATOR_REFERENCE};"
    f"tenant_id={TENANT_A};tenant_slug=tenant-a"
)


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


class _MappingSecrets:
    """Resolves from a table and records what it was asked for."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = values
        self.asked: list[str] = []

    async def resolve(self, reference: str) -> SecretStr:
        self.asked.append(reference)
        value = self._values.get(reference)
        if value is None:
            raise SecretResolutionError(reference)
        return SecretStr(value)


def _roster(value: str) -> tuple[PrincipalBinding, ...]:
    return admin_bindings_from({ADMIN_PRINCIPALS: value})


def _authenticator(
    value: str = f"{PLATFORM_ENTRY},{OPERATOR_ENTRY}",
    *,
    secrets: _MappingSecrets | None = None,
) -> tuple[ServiceTokenAuthenticator, _MappingSecrets]:
    resolver = secrets or _MappingSecrets(
        {
            PLATFORM_REFERENCE: PLATFORM_TOKEN,
            OPERATOR_REFERENCE: OPERATOR_TOKEN,
        }
    )
    return ServiceTokenAuthenticator(_roster(value), resolver), resolver


def test_roster_reads_principal_roles_tenant_and_reference() -> None:
    bindings = _roster(f"{PLATFORM_ENTRY},{OPERATOR_ENTRY}")
    assert [item.token_reference for item in bindings] == [
        PLATFORM_REFERENCE,
        OPERATOR_REFERENCE,
    ]
    platform, operator = (item.principal for item in bindings)
    assert platform.principal_id == PLATFORM_ID
    assert platform.roles == frozenset({"platform_admin"})
    assert platform.tenant_id is None
    assert platform.tenant_slug is None
    assert operator.roles == frozenset({"operator", "auditor"})
    assert operator.tenant_id == TENANT_A
    assert operator.tenant_slug == "tenant-a"


def test_a_numeric_slug_segment_is_a_slug() -> None:
    """The roster accepts every slug a tenant package may declare."""
    entry = f"{OPERATOR_ENTRY.rsplit('=', maxsplit=1)[0]}=sede-2"
    assert _roster(entry)[0].principal.tenant_slug == "sede-2"


def test_absent_or_blank_roster_binds_nobody() -> None:
    assert admin_bindings_from({}) == ()
    assert _roster("   ") == ()
    assert _roster(" , ") == ()


@pytest.mark.parametrize(
    "entry",
    [
        f"roles=platform_admin;secret={PLATFORM_REFERENCE}",
        f"principal={PLATFORM_ID};secret={PLATFORM_REFERENCE}",
        f"principal={PLATFORM_ID};roles=platform_admin",
        f"principal=not-a-uuid;roles=platform_admin;secret={PLATFORM_REFERENCE}",
        f"principal={PLATFORM_ID};roles=;secret={PLATFORM_REFERENCE}",
        f"principal={PLATFORM_ID};roles=root;secret={PLATFORM_REFERENCE}",
        f"principal={PLATFORM_ID};roles=platform_admin;secret=plain-token-value",
        f"principal={PLATFORM_ID};roles=platform_admin;token={PLATFORM_REFERENCE}",
        f"{PLATFORM_ENTRY};tenant_id={TENANT_A}",
        f"{PLATFORM_ENTRY};tenant_slug=tenant-a",
        f"{PLATFORM_ENTRY};tenant_id=not-a-uuid;tenant_slug=tenant-a",
        f"{PLATFORM_ENTRY};tenant_id={TENANT_A};tenant_slug=Tenant A",
        f"principal={PLATFORM_ID};roles=platform_admin;secret={PLATFORM_REFERENCE};roles=operator",
    ],
)
def test_a_malformed_entry_refuses_the_whole_roster(entry: str) -> None:
    """Fail closed and loudly: a typo must not silently bind fewer principals."""
    with pytest.raises(ValueError) as refused:
        _roster(entry)
    assert ADMIN_PRINCIPALS in str(refused.value)


def test_refusal_never_echoes_the_offending_entry() -> None:
    """The value may hold a pasted credential, so the failure never repeats it."""
    with pytest.raises(ValueError) as refused:
        _roster(f"principal={PLATFORM_ID};roles=platform_admin;secret={PLATFORM_TOKEN}")
    assert PLATFORM_TOKEN not in str(refused.value)


def test_presented_token_authenticates_its_own_principal() -> None:
    authenticator, _ = _authenticator()
    platform = _run(authenticator.authenticate(f"Bearer {PLATFORM_TOKEN}"))
    operator = _run(authenticator.authenticate(f"bearer {OPERATOR_TOKEN}"))
    assert platform is not None
    assert platform.principal_id == PLATFORM_ID
    assert operator is not None
    assert operator.principal_id == OPERATOR_ID
    assert operator.tenant_slug == "tenant-a"


@pytest.mark.parametrize(
    "credentials",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        f"Bearer {PLATFORM_TOKEN}x",
        f"Bearer {PLATFORM_TOKEN[:-1]}",
        PLATFORM_TOKEN,
        f"Basic {PLATFORM_TOKEN}",
        f"Token {PLATFORM_TOKEN}",
        f"Bearer {PLATFORM_TOKEN} {OPERATOR_TOKEN}",
    ],
)
def test_anything_but_the_exact_bearer_token_authenticates_nobody(
    credentials: str | None,
) -> None:
    authenticator, _ = _authenticator()
    assert _run(authenticator.authenticate(credentials)) is None


def test_an_unresolvable_binding_authenticates_nobody_and_spares_the_rest() -> None:
    """A misconfigured binding must not open the plane nor close the others."""
    secrets = _MappingSecrets({OPERATOR_REFERENCE: OPERATOR_TOKEN})
    authenticator, _ = _authenticator(secrets=secrets)
    assert _run(authenticator.authenticate(f"Bearer {PLATFORM_TOKEN}")) is None
    assert _run(authenticator.authenticate("Bearer ")) is None
    survivor = _run(authenticator.authenticate(f"Bearer {OPERATOR_TOKEN}"))
    assert survivor is not None
    assert survivor.principal_id == OPERATOR_ID


def test_an_empty_roster_authenticates_nobody() -> None:
    authenticator = ServiceTokenAuthenticator((), _MappingSecrets({}))
    assert _run(authenticator.authenticate(f"Bearer {PLATFORM_TOKEN}")) is None


def test_every_binding_is_compared_even_after_a_match() -> None:
    """No early exit: the work done must not depend on which token was sent."""
    authenticator, secrets = _authenticator()
    _run(authenticator.authenticate(f"Bearer {PLATFORM_TOKEN}"))
    matched_first = list(secrets.asked)
    secrets.asked.clear()
    _run(authenticator.authenticate(f"Bearer {OPERATOR_TOKEN}"))
    matched_last = list(secrets.asked)
    secrets.asked.clear()
    _run(authenticator.authenticate("Bearer nothing-matches-this"))
    assert matched_first == matched_last == list(secrets.asked)
    assert matched_first == [PLATFORM_REFERENCE, OPERATOR_REFERENCE]


def test_source_compares_tokens_in_constant_time() -> None:
    """`==` on a credential leaks its prefix through timing; the module bans it."""
    source = Path(service_token.__file__).read_text(encoding="utf-8")
    assert "compare_digest" in source
    assert "get_secret_value() ==" not in source


def test_neither_the_binding_nor_the_authenticator_holds_a_token_value() -> None:
    authenticator, _ = _authenticator()
    binding = _roster(PLATFORM_ENTRY)[0]
    _run(authenticator.authenticate(f"Bearer {PLATFORM_TOKEN}"))
    rendered = repr(binding) + repr(authenticator) + repr(binding.principal)
    assert PLATFORM_TOKEN not in rendered
    assert binding.token_reference == PLATFORM_REFERENCE


def test_authenticator_satisfies_the_published_protocol() -> None:
    authenticator, _ = _authenticator()
    assert isinstance(authenticator, AdminAuthenticator)
    assert not isinstance(object(), AdminAuthenticator)


def test_fallback_platform_admin_uses_the_resolvable_roster_entry() -> None:
    """Lab HTML may act as this principal when the browser sent no Bearer."""
    authenticator, secrets = _authenticator()
    principal = _run(authenticator.fallback_platform_admin())
    assert principal is not None
    assert principal.principal_id == PLATFORM_ID
    assert "platform_admin" in principal.roles
    assert principal.tenant_id is None
    assert PLATFORM_TOKEN not in repr(principal)
    assert PLATFORM_REFERENCE in secrets.asked


def test_fallback_platform_admin_is_none_when_the_secret_does_not_resolve() -> None:
    secrets = _MappingSecrets({OPERATOR_REFERENCE: OPERATOR_TOKEN})
    authenticator, _ = _authenticator(secrets=secrets)
    assert _run(authenticator.fallback_platform_admin()) is None


def test_fallback_platform_admin_skips_tenant_bound_and_non_platform_roles() -> None:
    authenticator, _ = _authenticator(OPERATOR_ENTRY)
    assert _run(authenticator.fallback_platform_admin()) is None
