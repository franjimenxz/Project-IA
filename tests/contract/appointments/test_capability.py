"""Contract suite for AppointmentCapability.

Deviation: pytest's builtin fixture is named `request`, so the create payload
fixture is `create_request`. Deviation: pytest-asyncio is not installed and
must not be added; tests wrap coroutines with asyncio.run.
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Callable, Coroutine
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from ia_mcp.contracts.appointments import (
    Appointment,
    AppointmentCancelRequest,
    AppointmentConfirmRequest,
    AppointmentCreateRequest,
    AppointmentGetRequest,
    AppointmentRescheduleRequest,
    AppointmentSearchRequest,
    AppointmentStatus,
)
from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp.capabilities.appointments import AppointmentCapability
from ia_mcp.tenancy.models import TenantContext

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("aaaaaaaa-0000-4000-8000-000000000001"),
)
TENANT_B_CTX = TenantContext(
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=UUID("bbbbbbbb-0000-4000-8000-000000000001"),
)

SENSITIVE_FRAGMENTS = (
    "tok-a-secret",
    "tok-b-secret",
    "secret-dni-999",
    "ada@example.com",
    "Ada Lovelace",
    "password",
    "Bearer ",
)

CapabilityFactory = Callable[..., AppointmentCapability]


def _run[T](coro: Coroutine[object, object, T]) -> T:
    return asyncio.run(coro)


def _assert_no_secrets(result: object) -> None:
    dumped = str(result)
    if hasattr(result, "model_dump_json"):
        dumped = f"{dumped} {result.model_dump_json()}"
    lowered = dumped.lower()
    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment.lower() not in lowered


def _search_cardiologia() -> AppointmentSearchRequest:
    return AppointmentSearchRequest(
        specialty="cardiologia",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 1),
    )


def _require_appointment(result: ToolResult[Appointment]) -> Appointment:
    assert result.ok is True
    assert result.value is not None
    return result.value


def _create(
    capability: AppointmentCapability,
    create_request: AppointmentCreateRequest,
    key: str = "k-1",
) -> Appointment:
    return _require_appointment(
        _run(capability.create(TENANT_A_CTX, create_request, idempotency_key=key))
    )


@pytest.mark.contract
def test_create_is_idempotent(
    appointment_capability: AppointmentCapability,
    create_request: AppointmentCreateRequest,
) -> None:
    async def scenario() -> None:
        first = await appointment_capability.create(
            TENANT_A_CTX, create_request, idempotency_key="k-1"
        )
        second = await appointment_capability.create(
            TENANT_A_CTX, create_request, idempotency_key="k-1"
        )
        assert first == second
        assert first.ok is True

    _run(scenario())


@pytest.mark.contract
def test_replay_create_does_not_book_a_second_appointment(
    appointment_capability: AppointmentCapability,
    create_request: AppointmentCreateRequest,
) -> None:
    first = _create(appointment_capability, create_request, "k-1")
    replay = _require_appointment(
        _run(
            appointment_capability.create(
                TENANT_A_CTX, create_request, idempotency_key="k-1"
            )
        )
    )
    assert replay.appointment_id == first.appointment_id
    conflict = _run(
        appointment_capability.create(
            TENANT_A_CTX, create_request, idempotency_key="k-2"
        )
    )
    assert conflict.ok is False
    assert conflict.error is not None
    assert conflict.error.code == ToolErrorCode.CONFLICT
    fetched = _require_appointment(
        _run(
            appointment_capability.get(
                TENANT_A_CTX,
                AppointmentGetRequest(appointment_id=first.appointment_id),
            )
        )
    )
    assert fetched.appointment_id == first.appointment_id


@pytest.mark.contract
def test_search_returns_tenant_slots(
    appointment_capability: AppointmentCapability,
) -> None:
    result = _run(appointment_capability.search(TENANT_A_CTX, _search_cardiologia()))
    assert result.ok is True
    assert result.value is not None
    assert [slot.slot_id for slot in result.value] == ["slot-a-1", "slot-a-2"]
    other = _run(appointment_capability.search(TENANT_B_CTX, _search_cardiologia()))
    assert other.ok is True
    assert other.value is not None
    assert [slot.slot_id for slot in other.value] == ["slot-b-1"]


@pytest.mark.contract
def test_get_create_cancel_reschedule_confirm_happy_paths(
    appointment_capability: AppointmentCapability,
    create_request: AppointmentCreateRequest,
) -> None:
    created = _create(appointment_capability, create_request, "k-create")
    assert created.status is AppointmentStatus.SCHEDULED
    fetched = _require_appointment(
        _run(
            appointment_capability.get(
                TENANT_A_CTX,
                AppointmentGetRequest(appointment_id=created.appointment_id),
            )
        )
    )
    assert fetched == created

    confirmed = _require_appointment(
        _run(
            appointment_capability.confirm(
                TENANT_A_CTX,
                AppointmentConfirmRequest(appointment_id=created.appointment_id),
                idempotency_key="k-confirm",
            )
        )
    )
    assert confirmed.status is AppointmentStatus.CONFIRMED

    rescheduled = _require_appointment(
        _run(
            appointment_capability.reschedule(
                TENANT_A_CTX,
                AppointmentRescheduleRequest(
                    appointment_id=created.appointment_id,
                    new_slot_id="slot-a-2",
                ),
                idempotency_key="k-reschedule",
            )
        )
    )
    assert rescheduled.status is AppointmentStatus.RESCHEDULED
    assert rescheduled.starts_at.hour == 14

    cancelled = _require_appointment(
        _run(
            appointment_capability.cancel(
                TENANT_A_CTX,
                AppointmentCancelRequest(appointment_id=created.appointment_id),
                idempotency_key="k-cancel",
            )
        )
    )
    assert cancelled.status is AppointmentStatus.CANCELLED


@pytest.mark.contract
def test_cross_tenant_get_and_cancel_are_not_found(
    appointment_capability: AppointmentCapability,
    create_request: AppointmentCreateRequest,
) -> None:
    created = _create(appointment_capability, create_request)
    get_result = _run(
        appointment_capability.get(
            TENANT_B_CTX,
            AppointmentGetRequest(appointment_id=created.appointment_id),
        )
    )
    unknown = _run(
        appointment_capability.get(
            TENANT_B_CTX,
            AppointmentGetRequest(appointment_id="does-not-exist"),
        )
    )
    cancel_result = _run(
        appointment_capability.cancel(
            TENANT_B_CTX,
            AppointmentCancelRequest(appointment_id=created.appointment_id),
            idempotency_key="k-cross",
        )
    )
    assert get_result.ok is False
    assert unknown.ok is False
    assert cancel_result.ok is False
    assert get_result.error is not None
    assert unknown.error is not None
    assert cancel_result.error is not None
    assert get_result.error.code == ToolErrorCode.NOT_FOUND
    assert unknown.error.code == ToolErrorCode.NOT_FOUND
    assert cancel_result.error.code == ToolErrorCode.NOT_FOUND
    assert get_result.error.safe_message == unknown.error.safe_message
    _assert_no_secrets(get_result)
    _assert_no_secrets(cancel_result)
    still_there = _require_appointment(
        _run(
            appointment_capability.get(
                TENANT_A_CTX,
                AppointmentGetRequest(appointment_id=created.appointment_id),
            )
        )
    )
    assert still_there.status is AppointmentStatus.SCHEDULED


@pytest.mark.contract
def test_slot_conflict_returns_conflict(
    appointment_capability: AppointmentCapability,
    create_request: AppointmentCreateRequest,
) -> None:
    _create(appointment_capability, create_request, "k-1")
    result = _run(
        appointment_capability.create(
            TENANT_A_CTX, create_request, idempotency_key="k-2"
        )
    )
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ToolErrorCode.CONFLICT
    _assert_no_secrets(result)


@pytest.mark.contract
@pytest.mark.parametrize(
    ("fault", "code", "retryable"),
    [
        ("timeout", ToolErrorCode.UPSTREAM_TIMEOUT, True),
        ("rate_limit", ToolErrorCode.RATE_LIMITED, True),
        ("malformed", ToolErrorCode.CONTRACT_VIOLATION, False),
    ],
)
def test_fault_plan_returns_typed_error_without_secrets(
    make_appointment_capability: CapabilityFactory,
    create_request: AppointmentCreateRequest,
    fault: str,
    code: ToolErrorCode,
    retryable: bool,
) -> None:
    capability = make_appointment_capability(fault=fault)
    created = _run(
        capability.create(TENANT_A_CTX, create_request, idempotency_key="k-fault")
    )
    searched = _run(capability.search(TENANT_A_CTX, _search_cardiologia()))
    for result in (created, searched):
        assert result.ok is False
        assert result.error is not None
        assert result.error.code == code
        assert result.error.retryable is retryable
        _assert_no_secrets(result)


@pytest.mark.contract
def test_only_valid_status_transitions_are_allowed(
    appointment_capability: AppointmentCapability,
    create_request: AppointmentCreateRequest,
) -> None:
    created = _create(appointment_capability, create_request, "k-create")
    confirmed = _require_appointment(
        _run(
            appointment_capability.confirm(
                TENANT_A_CTX,
                AppointmentConfirmRequest(appointment_id=created.appointment_id),
                idempotency_key="k-confirm-1",
            )
        )
    )
    assert confirmed.status is AppointmentStatus.CONFIRMED
    already_confirmed = _require_appointment(
        _run(
            appointment_capability.confirm(
                TENANT_A_CTX,
                AppointmentConfirmRequest(appointment_id=created.appointment_id),
                idempotency_key="k-confirm-2",
            )
        )
    )
    assert already_confirmed.status is AppointmentStatus.CONFIRMED
    cancelled = _require_appointment(
        _run(
            appointment_capability.cancel(
                TENANT_A_CTX,
                AppointmentCancelRequest(appointment_id=created.appointment_id),
                idempotency_key="k-cancel-1",
            )
        )
    )
    assert cancelled.status is AppointmentStatus.CANCELLED
    already_cancelled = _require_appointment(
        _run(
            appointment_capability.cancel(
                TENANT_A_CTX,
                AppointmentCancelRequest(appointment_id=created.appointment_id),
                idempotency_key="k-cancel-2",
            )
        )
    )
    assert already_cancelled.status is AppointmentStatus.CANCELLED
    confirm_cancelled = _run(
        appointment_capability.confirm(
            TENANT_A_CTX,
            AppointmentConfirmRequest(appointment_id=created.appointment_id),
            idempotency_key="k-confirm-cancelled",
        )
    )
    reschedule_cancelled = _run(
        appointment_capability.reschedule(
            TENANT_A_CTX,
            AppointmentRescheduleRequest(
                appointment_id=created.appointment_id,
                new_slot_id="slot-a-2",
            ),
            idempotency_key="k-reschedule-cancelled",
        )
    )
    assert confirm_cancelled.ok is False
    assert reschedule_cancelled.ok is False
    assert confirm_cancelled.error is not None
    assert reschedule_cancelled.error is not None
    assert confirm_cancelled.error.code == ToolErrorCode.CONFLICT
    assert reschedule_cancelled.error.code == ToolErrorCode.CONFLICT


@pytest.mark.contract
def test_suite_depends_on_protocol_not_fake_class() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert all("fakes" not in name for name in imported)
    assert "ia_mcp.mcp.capabilities.appointments" in imported
    assert "AppointmentCapability" in imported
