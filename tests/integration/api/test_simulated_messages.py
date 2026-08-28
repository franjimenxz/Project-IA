from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from ia_mcp.api.app import create_app
from ia_mcp.tenancy.models import ChannelIntegration, TenantIdentity
from ia_mcp.tenancy.service import TenantService

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
FROZEN_NOW = datetime(2026, 8, 28, 4, 20, 0, tzinfo=UTC)
SIMULATED_HMAC_SECRET = b"ia-mcp-simulated-non-production-secret"
ACCOUNT_HEADER = "X-Simulated-Account"
TIMESTAMP_HEADER = "X-Simulated-Timestamp"
SIGNATURE_HEADER = "X-Simulated-Signature"


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


class RecordingTenantService:
    def __init__(self, inner: TenantService) -> None:
        self._inner = inner
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, channel: str, account_id: str) -> TenantIdentity:
        self.calls.append((channel, account_id))
        return await self._inner.resolve(channel, account_id)


def encode_simulated_body(body: dict[str, Any]) -> bytes:
    return json.dumps(
        body, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sign_simulated(account: str, timestamp: str, body: bytes) -> str:
    payload = f"{account}.{timestamp}.".encode() + body
    return hmac.new(SIMULATED_HMAC_SECRET, payload, hashlib.sha256).hexdigest()


def signed_simulated_headers(
    *,
    account: str,
    body: dict[str, Any],
    now: datetime = FROZEN_NOW,
) -> dict[str, str]:
    timestamp = str(int(now.timestamp()))
    signature = sign_simulated(account, timestamp, encode_simulated_body(body))
    return {
        ACCOUNT_HEADER: account,
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: signature,
    }


def valid_body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "external_message_id": "m-1",
        "external_user_id": "u-1",
        "text": "tenant_b",
    }
    payload.update(overrides)
    return payload


def make_client(
    *,
    environment: str | None = "test",
    mapping: dict[tuple[str, str], UUID] | None = None,
    clock: datetime = FROZEN_NOW,
) -> tuple[TestClient, RecordingTenantService]:
    kwargs: dict[str, Any] = {}
    if environment is not None:
        kwargs["environment"] = environment
    app = create_app(**kwargs)
    repo = FakeChannelRepository(
        mapping or {("simulated", "acct-a"): TENANT_A, ("simulated", "acct-b"): TENANT_B}
    )
    recorder = RecordingTenantService(TenantService(repo))
    app.state.tenant_service = recorder
    app.state.simulated_clock = lambda: clock
    return TestClient(app), recorder


@pytest.fixture
def client() -> Iterator[TestClient]:
    # "test" keeps the ACK contract: the app must not auto-wire a harness even
    # when the developer's shell exports DATABASE_URL.
    app = create_app(environment="test")
    repo = FakeChannelRepository({("simulated", "acct-a"): TENANT_A})
    recorder = RecordingTenantService(TenantService(repo))
    app.state.tenant_service = recorder
    app.state.simulated_clock = lambda: FROZEN_NOW
    yield TestClient(app)


def test_simulated_message_resolves_tenant_from_account(client: TestClient) -> None:
    body = {"external_message_id": "m-1", "external_user_id": "u-1", "text": "tenant_b"}
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    response = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert response.status_code == 202
    assert response.json()["tenant_slug"] == "tenant-a"


def test_unknown_account_returns_safe_error() -> None:
    client, recorder = make_client()
    body = valid_body()
    headers = signed_simulated_headers(account="acct-unknown", body=body, now=FROZEN_NOW)
    response = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert response.status_code == 400
    assert recorder.calls == [("simulated", "acct-unknown")]
    payload = response.json()
    assert "tenant-a" not in response.text
    assert "tenant-b" not in response.text
    detail = str(payload)
    assert "traceback" not in detail.lower()
    assert "secret" not in detail.lower()


def test_extra_tenant_id_in_body_is_rejected() -> None:
    client, recorder = make_client()
    body = valid_body(tenant_id=str(TENANT_B))
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    response = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert response.status_code == 422
    assert recorder.calls == []


def test_extra_account_id_in_body_is_rejected() -> None:
    client, recorder = make_client()
    body = valid_body(account_id="acct-b")
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    response = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert response.status_code == 422
    assert recorder.calls == []
