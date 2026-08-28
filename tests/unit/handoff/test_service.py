from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from ia_mcp.conversation.models import Conversation
from ia_mcp.handoff.adapters.fake import FakeHandoffAdapter
from ia_mcp.handoff.models import HandoffRequest
from ia_mcp.handoff.ports import HandoffError
from ia_mcp.handoff.service import HandoffService
from ia_mcp.tenancy.models import TenantContext
from tests.unit.handoff.fakes import InMemoryHandoffRepository

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CHANNEL_A = UUID("aa111111-1111-1111-1111-111111111111")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
TENANT_B_CTX = TenantContext(
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=UUID("44444444-4444-4444-4444-444444444444"),
)
REASONS = (
    "explicit_request",
    "insufficient_knowledge",
    "persistent_error",
    "out_of_scope",
    "policy",
    "low_confidence",
    "manual_review_required",
)


def _conversation(tenant_id: UUID = TENANT_A) -> Conversation:
    return Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        channel_integration_id=CHANNEL_A if tenant_id == TENANT_A else uuid4(),
        status="bot_owned",
        last_message_at=datetime.now(UTC),
        lock_version=1,
    )


def _request(
    conversation_id: UUID,
    *,
    reason: str = "explicit_request",
    business_key: str = "handoff:conv-a",
    **kwargs: object,
) -> HandoffRequest:
    return HandoffRequest(
        conversation_id=conversation_id,
        reason=reason,  # type: ignore[arg-type]
        business_key=business_key,
        **kwargs,  # type: ignore[arg-type]
    )


def _service(
    repository: InMemoryHandoffRepository | None = None,
    provider: FakeHandoffAdapter | None = None,
) -> tuple[HandoffService, InMemoryHandoffRepository, FakeHandoffAdapter]:
    repository = repository or InMemoryHandoffRepository()
    provider = provider or FakeHandoffAdapter()
    return HandoffService(repository, provider), repository, provider


@pytest.mark.anyio
async def test_explicit_request_creates_typed_handoff() -> None:
    service, repository, provider = _service()
    conversation = _conversation()
    repository.seed_conversation(conversation)
    result = await service.create(
        TENANT_A_CTX, _request(conversation.id, reason="explicit_request")
    )
    assert result.reason == "explicit_request"
    assert result.replayed is False
    assert result.tenant_id == TENANT_A
    assert result.conversation_id == conversation.id
    assert result.status in {"requested", "accepted"}
    assert await repository.conversation_status(TENANT_A_CTX, conversation.id) == (
        "human_owned"
    )
    assert provider.cases_for(TENANT_A_CTX)
    assert provider.cases_for(TENANT_A_CTX)[0].reason == "explicit_request"


@pytest.mark.anyio
@pytest.mark.parametrize("reason", REASONS)
async def test_typed_triggers_are_persisted(reason: str) -> None:
    service, repository, _provider = _service()
    conversation = _conversation()
    repository.seed_conversation(conversation)
    result = await service.create(
        TENANT_A_CTX,
        _request(conversation.id, reason=reason, business_key=f"handoff:{reason}"),
    )
    assert result.reason == reason
    assert result.summary.reason == reason


@pytest.mark.anyio
async def test_summary_contains_collected_fields_and_actions_sanitized() -> None:
    service, repository, provider = _service()
    conversation = _conversation()
    repository.seed_conversation(conversation)
    result = await service.create(
        TENANT_A_CTX,
        _request(
            conversation.id,
            patient_reference="patient-a@example.com",
            collected_fields={
                "name": "Ana",
                "password": "supersecret",
                "api_token": "tok-1",
                "specialty": "cardiology",
            },
            completed_actions=("search_slots",),
            notes="Contact ana@clinic.test with Bearer SUPERSECRET",
        ),
    )
    dumped = str(result.summary.as_payload())
    assert "Ana" in dumped or result.summary.collected_fields["name"] == "Ana"
    assert result.summary.collected_fields["specialty"] == "cardiology"
    assert "search_slots" in result.summary.completed_actions
    assert "supersecret" not in dumped
    assert "password" not in dumped
    assert "tok-1" not in dumped
    assert "ana@clinic.test" not in dumped
    assert "SUPERSECRET" not in dumped
    assert "[EMAIL]" in (result.summary.patient_reference or "")
    outbox = await repository.list_outbox(TENANT_A_CTX, kind="handoff.requested")
    assert len(outbox) == 1
    outbox_dump = str(outbox[0].payload)
    assert "supersecret" not in outbox_dump
    assert "password" not in outbox_dump
    delivered = provider.cases_for(TENANT_A_CTX)[0]
    assert "supersecret" not in str(delivered.summary.as_payload())


@pytest.mark.anyio
async def test_create_and_ownership_are_atomic() -> None:
    service, repository, _provider = _service()
    conversation = _conversation()
    repository.seed_conversation(conversation)
    result = await service.create(TENANT_A_CTX, _request(conversation.id))
    assert result.handoff_id is not None
    assert await repository.conversation_status(TENANT_A_CTX, conversation.id) == (
        "human_owned"
    )
    assert await repository.count_cases(TENANT_A_CTX) == 1
    assert await repository.list_outbox(TENANT_A_CTX, kind="handoff.requested")
    with pytest.raises(HandoffError) as caught:
        await service.create(
            TENANT_A_CTX,
            _request(uuid4(), business_key="handoff:missing"),
        )
    assert caught.value.code == "not_found"
    assert await repository.count_cases(TENANT_A_CTX) == 1
    assert (
        len(await repository.list_outbox(TENANT_A_CTX, kind="handoff.requested")) == 1
    )


@pytest.mark.anyio
async def test_replay_returns_same_case_without_second_row() -> None:
    service, repository, _provider = _service()
    conversation = _conversation()
    repository.seed_conversation(conversation)
    first = await service.create(
        TENANT_A_CTX, _request(conversation.id, business_key="handoff:dup")
    )
    second = await service.create(
        TENANT_A_CTX, _request(conversation.id, business_key="handoff:dup")
    )
    assert second.handoff_id == first.handoff_id
    assert second.replayed is True
    assert await repository.count_cases(TENANT_A_CTX) == 1
    assert (
        len(await repository.list_outbox(TENANT_A_CTX, kind="handoff.requested")) == 1
    )


@pytest.mark.anyio
async def test_provider_down_keeps_durable_outbox() -> None:
    repository = InMemoryHandoffRepository()
    provider = FakeHandoffAdapter(available=False)
    service = HandoffService(repository, provider)
    conversation = _conversation()
    repository.seed_conversation(conversation)
    result = await service.create(TENANT_A_CTX, _request(conversation.id))
    assert result.delivery_pending is True
    assert await repository.conversation_status(TENANT_A_CTX, conversation.id) == (
        "human_owned"
    )
    assert await repository.count_cases(TENANT_A_CTX) == 1
    outbox = await repository.list_outbox(TENANT_A_CTX, kind="handoff.requested")
    assert len(outbox) == 1
    assert provider.cases_for(TENANT_A_CTX) == ()


@pytest.mark.anyio
async def test_operator_a_does_not_receive_case_b() -> None:
    service, repository, provider = _service()
    conversation_a = _conversation(TENANT_A)
    conversation_b = _conversation(TENANT_B)
    repository.seed_conversation(conversation_a)
    repository.seed_conversation(conversation_b)
    await service.create(
        TENANT_A_CTX,
        _request(conversation_a.id, business_key="handoff:a"),
    )
    await service.create(
        TENANT_B_CTX,
        _request(conversation_b.id, business_key="handoff:b"),
    )
    assert all(item.reason for item in provider.cases_for(TENANT_A_CTX))
    a_ids = {item.handoff_id for item in provider.cases_for(TENANT_A_CTX)}
    b_ids = {item.handoff_id for item in provider.cases_for(TENANT_B_CTX)}
    assert a_ids.isdisjoint(b_ids)
    loaded = await repository.get_by_business_key(TENANT_B_CTX, "handoff:a")
    assert loaded is None


@pytest.mark.anyio
async def test_invalid_reason_is_rejected() -> None:
    service, repository, _provider = _service()
    conversation = _conversation()
    repository.seed_conversation(conversation)
    with pytest.raises(HandoffError) as caught:
        await service.create(
            TENANT_A_CTX, _request(conversation.id, reason="not_a_reason")
        )
    assert caught.value.code == "invalid_reason"
    assert await repository.count_cases(TENANT_A_CTX) == 0
