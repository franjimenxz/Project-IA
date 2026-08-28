from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import pytest
from pydantic import SecretStr

from ia_mcp.contracts.appointments import (
    AppointmentCreateRequest,
    AppointmentSlot,
    PatientRef,
)
from ia_mcp.mcp.capabilities.appointments import AppointmentCapability
from ia_mcp.mcp.fakes.appointments import FakeAppointmentCapability, FaultPlan
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

FIXED_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SLOT_A_1 = AppointmentSlot(
    slot_id="slot-a-1",
    starts_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
    ends_at=datetime(2026, 9, 1, 13, 30, tzinfo=UTC),
    specialty="cardiologia",
    practitioner="Dr. Ada",
    location="sede-centro",
    booking_token=SecretStr("tok-a-secret"),
)
SLOT_A_2 = AppointmentSlot(
    slot_id="slot-a-2",
    starts_at=datetime(2026, 9, 1, 14, 0, tzinfo=UTC),
    ends_at=datetime(2026, 9, 1, 14, 30, tzinfo=UTC),
    specialty="cardiologia",
    practitioner="Dr. Ada",
    location="sede-centro",
    booking_token=SecretStr("tok-a-secret-2"),
)
SLOT_A_3 = AppointmentSlot(
    slot_id="slot-a-3",
    starts_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
    ends_at=datetime(2026, 9, 2, 10, 30, tzinfo=UTC),
    specialty="dermatologia",
    practitioner="Dr. Beau",
    location="sede-norte",
)
SLOT_B_1 = AppointmentSlot(
    slot_id="slot-b-1",
    starts_at=datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
    ends_at=datetime(2026, 9, 1, 13, 30, tzinfo=UTC),
    specialty="cardiologia",
    practitioner="Dr. Ada",
    location="sede-centro",
    booking_token=SecretStr("tok-b-secret"),
)

DEFAULT_SLOTS = {
    TENANT_A: (SLOT_A_1, SLOT_A_2, SLOT_A_3),
    TENANT_B: (SLOT_B_1,),
}

FaultName = Literal["timeout", "rate_limit", "malformed"]


def _id_factory() -> Callable[[], str]:
    counter = iter(range(1, 10_000))
    return lambda: f"apt-{next(counter)}"


@pytest.fixture
def create_request() -> AppointmentCreateRequest:
    # Named create_request because pytest's builtin fixture is `request`.
    return AppointmentCreateRequest(
        slot_id="slot-a-1",
        booking_token=SecretStr("tok-a-secret"),
        patient=PatientRef(
            external_patient_id="pat-ext-1",
            document_type="DNI",
            document_number=SecretStr("secret-dni-999"),
            name="Ada Lovelace",
            email="ada@example.com",
        ),
        coverage="osde",
        contact_email="ada@example.com",
    )


@pytest.fixture
def make_appointment_capability() -> Callable[..., AppointmentCapability]:
    def factory(
        *,
        fault: FaultName | None = None,
        fault_operations: frozenset[str] | None = None,
    ) -> AppointmentCapability:
        return FakeAppointmentCapability(
            clock=lambda: FIXED_NOW,
            id_factory=_id_factory(),
            fault_plan=(
                None
                if fault is None
                else FaultPlan(fault=fault, operations=fault_operations)
            ),
            initial_slots=DEFAULT_SLOTS,
        )

    return factory


@pytest.fixture
def appointment_capability(
    make_appointment_capability: Callable[..., AppointmentCapability],
) -> Iterator[AppointmentCapability]:
    yield make_appointment_capability()
