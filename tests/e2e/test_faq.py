from __future__ import annotations

from uuid import UUID

import pytest

from tests.e2e.conftest import post_faq


@pytest.mark.anyio
@pytest.mark.e2e
async def test_tenants_receive_distinct_faq_answers_and_source_ids(faq_stack) -> None:
    client, outbox, clock = faq_stack
    response_a = await post_faq(
        client, account="acct-a", text="hours", external_message_id="m-a", now=clock.now
    )
    clock.tick()
    response_b = await post_faq(
        client, account="acct-b", text="hours", external_message_id="m-b", now=clock.now
    )
    assert response_a.status_code == 202
    assert response_b.status_code == 202
    body_a = response_a.json()
    body_b = response_b.json()
    assert body_a["tenant_slug"] == "tenant-a"
    assert body_b["tenant_slug"] == "tenant-b"
    assert body_a["kind"] == "answer"
    assert body_b["kind"] == "answer"
    assert body_a["source_ids"]
    assert body_b["source_ids"]
    assert body_a["source_ids"] != body_b["source_ids"]
    assert "canary-a" in body_a["text"]
    assert "canary-b" in body_b["text"]
    assert "canary-b" not in body_a["text"]
    assert "canary-a" not in body_b["text"]
    header_a = response_a.headers["x-correlation-id"]
    header_b = response_b.headers["x-correlation-id"]
    assert body_a["correlation_id"] == header_a
    assert body_b["correlation_id"] == header_b
    assert header_a != header_b
    assert body_a["config_version"] == 1
    assert body_b["config_version"] == 1
    deliveries = outbox.list()
    assert len(deliveries) == 2
    assert {item.tenant_slug for item in deliveries} == {"tenant-a", "tenant-b"}
    by_slug = {item.tenant_slug: item for item in deliveries}
    assert str(by_slug["tenant-a"].correlation_id) == header_a
    assert str(by_slug["tenant-b"].correlation_id) == header_b
    assert {tuple(item.source_ids) for item in deliveries} == {
        tuple(body_a["source_ids"]),
        tuple(body_b["source_ids"]),
    }


@pytest.mark.anyio
@pytest.mark.e2e
async def test_duplicate_external_message_reuses_run_and_outbox(faq_stack) -> None:
    client, outbox, clock = faq_stack
    first = await post_faq(
        client, account="acct-a", text="hours", external_message_id="m-dup", now=clock.now
    )
    clock.tick()
    second = await post_faq(
        client,
        account="acct-a",
        text="hours",
        external_message_id="m-dup",
        now=clock.now,
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["source_ids"] == second.json()["source_ids"]
    assert len(outbox.list()) == 1


@pytest.mark.anyio
@pytest.mark.e2e
async def test_forged_correlation_header_is_ignored(faq_stack) -> None:
    client, outbox, clock = faq_stack
    forged = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    response = await post_faq(
        client,
        account="acct-a",
        text="hours",
        external_message_id="m-forged",
        now=clock.now,
        correlation_id=forged,
    )
    assert response.status_code == 202
    body = response.json()
    header = response.headers["x-correlation-id"]
    assert body["correlation_id"] == header
    assert body["correlation_id"] != str(forged)
    deliveries = outbox.list()
    assert len(deliveries) == 1
    assert str(deliveries[0].correlation_id) == header
