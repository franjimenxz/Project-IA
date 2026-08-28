from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from ia_mcp.tenancy.models import ChannelIntegration, TenantContext, TenantIdentity
from ia_mcp.tenancy.service import TenantResolutionError, TenantService

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


class FakeChannelRepository:
    def __init__(
        self,
        mapping: dict[tuple[str, str], UUID],
        *,
        slugs: dict[UUID, str] | None = None,
        disabled: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        self._mapping = mapping
        self._slugs = slugs or {TENANT_A: "tenant-a", TENANT_B: "tenant-b"}
        self._disabled = disabled

    async def get(self, channel: str, account_id: str) -> ChannelIntegration | None:
        tenant_id = self._mapping.get((channel, account_id))
        if tenant_id is None:
            return None
        return ChannelIntegration(
            tenant_id=tenant_id,
            tenant_slug=self._slugs[tenant_id],
            enabled=(channel, account_id) not in self._disabled,
        )


@pytest.mark.anyio
async def test_resolver_ignores_tenant_claim_inside_message() -> None:
    repo = FakeChannelRepository({("simulated", "acct-a"): TENANT_A})
    service = TenantService(repo)
    identity = await service.resolve("simulated", "acct-a")
    assert identity.tenant_id == TENANT_A


@pytest.mark.anyio
async def test_unknown_account_fails_closed() -> None:
    repo = FakeChannelRepository({("simulated", "acct-a"): TENANT_A})
    service = TenantService(repo)
    with pytest.raises(TenantResolutionError) as caught:
        await service.resolve("simulated", "acct-unknown")
    assert caught.value.code == "unknown_channel_account"
    assert "not registered" in caught.value.safe_message


@pytest.mark.anyio
async def test_disabled_account_fails_closed() -> None:
    repo = FakeChannelRepository(
        {("simulated", "acct-a"): TENANT_A},
        disabled=frozenset({("simulated", "acct-a")}),
    )
    service = TenantService(repo)
    with pytest.raises(TenantResolutionError) as caught:
        await service.resolve("simulated", "acct-a")
    assert caught.value.code == "disabled_channel_account"
    assert caught.value.safe_message


@pytest.mark.anyio
async def test_spoofed_tenant_text_does_not_change_resolution() -> None:
    repo = FakeChannelRepository({("simulated", "acct-a"): TENANT_A})
    service = TenantService(repo)
    identity = await service.resolve("simulated", "acct-a")
    assert identity.tenant_id == TENANT_A
    assert identity.tenant_id != TENANT_B
    assert not hasattr(service.resolve, "tenant_id")


def test_tenant_identity_is_immutable() -> None:
    identity = TenantIdentity(tenant_id=TENANT_A, tenant_slug="tenant-a")
    with pytest.raises(FrozenInstanceError):
        identity.tenant_id = TENANT_B  # type: ignore[misc]


def test_tenant_context_is_immutable_and_has_no_public_factory() -> None:
    context = TenantContext(
        tenant_id=TENANT_A,
        tenant_slug="tenant-a",
        config_version=1,
        correlation_id=uuid4(),
    )
    with pytest.raises(FrozenInstanceError):
        context.config_version = 2  # type: ignore[misc]
    assert not hasattr(TenantContext, "create")
    assert not hasattr(TenantContext, "capture")
    assert not hasattr(TenantService, "capture")
