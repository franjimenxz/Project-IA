from __future__ import annotations

from datetime import timedelta

from tests.integration.api.test_simulated_messages import (
    FROZEN_NOW,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    make_client,
    signed_simulated_headers,
    valid_body,
)


def test_tampered_body_rejects_signature_before_resolve() -> None:
    client, recorder = make_client()
    body = valid_body()
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    tampered = valid_body(text="tenant-a-please")
    response = client.post("/v1/simulated/messages", json=tampered, headers=headers)
    assert response.status_code == 401
    assert recorder.calls == []


def test_tampered_account_rejects_signature_before_resolve() -> None:
    client, recorder = make_client()
    body = valid_body()
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    headers = {**headers, "X-Simulated-Account": "acct-b"}
    response = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert response.status_code == 401
    assert recorder.calls == []


def test_tampered_timestamp_rejects_signature_before_resolve() -> None:
    client, recorder = make_client()
    body = valid_body()
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    later = FROZEN_NOW + timedelta(seconds=1)
    headers = {**headers, TIMESTAMP_HEADER: str(int(later.timestamp()))}
    response = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert response.status_code == 401
    assert recorder.calls == []


def test_stale_timestamp_rejects_before_resolve() -> None:
    client, recorder = make_client()
    body = valid_body()
    stale = FROZEN_NOW - timedelta(seconds=301)
    headers = signed_simulated_headers(account="acct-a", body=body, now=stale)
    response = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert response.status_code == 401
    assert recorder.calls == []


def test_replayed_request_rejects_before_second_resolve() -> None:
    client, recorder = make_client()
    body = valid_body()
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    first = client.post("/v1/simulated/messages", json=body, headers=headers)
    second = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 401
    assert recorder.calls == [("simulated", "acct-a")]


def test_simulated_route_omitted_in_production() -> None:
    production, prod_recorder = make_client(environment="production")
    development, dev_recorder = make_client(environment="development")
    body = valid_body()
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    prod_response = production.post("/v1/simulated/messages", json=body, headers=headers)
    dev_response = development.post("/v1/simulated/messages", json=body, headers=headers)
    assert prod_response.status_code == 404
    assert prod_recorder.calls == []
    assert "/v1/simulated/messages" not in {
        getattr(route, "path", "") for route in production.app.routes
    }
    assert dev_response.status_code == 202
    assert dev_recorder.calls == [("simulated", "acct-a")]
    assert dev_response.json()["tenant_slug"] == "tenant-a"


def test_invalid_signature_header_rejects_before_resolve() -> None:
    client, recorder = make_client()
    body = valid_body()
    headers = signed_simulated_headers(account="acct-a", body=body, now=FROZEN_NOW)
    headers = {**headers, SIGNATURE_HEADER: "0" * 64}
    response = client.post("/v1/simulated/messages", json=body, headers=headers)
    assert response.status_code == 401
    assert recorder.calls == []
