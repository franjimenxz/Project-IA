"""In-memory appointment capability for tests. Never a production adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from ia_mcp.contracts.appointments import (
    Appointment,
    AppointmentCancelRequest,
    AppointmentConfirmRequest,
    AppointmentCreateRequest,
    AppointmentGetRequest,
    AppointmentRescheduleRequest,
    AppointmentSearchRequest,
    AppointmentSlot,
    AppointmentStatus,
)
from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolError, ToolErrorCode
from ia_mcp.tenancy.models import TenantContext

Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
FaultName = Literal["timeout", "rate_limit", "malformed"]

_ACTIVE_STATUSES = frozenset(
    {
        AppointmentStatus.SCHEDULED,
        AppointmentStatus.PENDING_CONFIRMATION,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.RESCHEDULED,
    }
)
_CONFIRMABLE = frozenset(
    {
        AppointmentStatus.SCHEDULED,
        AppointmentStatus.PENDING_CONFIRMATION,
        AppointmentStatus.RESCHEDULED,
        AppointmentStatus.CONFIRMED,
    }
)

_NOT_FOUND = ToolError(
    code=ToolErrorCode.NOT_FOUND,
    retryable=False,
    safe_message="The requested resource was not found.",
)
_CONFLICT = ToolError(
    code=ToolErrorCode.CONFLICT,
    retryable=False,
    safe_message="The requested slot is not available.",
)
_INVALID_TRANSITION = ToolError(
    code=ToolErrorCode.CONFLICT,
    retryable=False,
    safe_message="The requested status transition is not allowed.",
)
_TIMEOUT = ToolError(
    code=ToolErrorCode.UPSTREAM_TIMEOUT,
    retryable=True,
    safe_message="The request timed out.",
)
_RATE_LIMITED = ToolError(
    code=ToolErrorCode.RATE_LIMITED,
    retryable=True,
    safe_message="Rate limit exceeded.",
)
_MALFORMED = ToolError(
    code=ToolErrorCode.CONTRACT_VIOLATION,
    retryable=False,
    safe_message="Upstream response was invalid.",
)


@dataclass(frozen=True, slots=True)
class FaultPlan:
    fault: FaultName
    operations: frozenset[str] | None = None


class _TenantAgenda:
    def __init__(self) -> None:
        self.slots: dict[str, AppointmentSlot] = {}
        self.appointments: dict[str, Appointment] = {}
        self.slot_of: dict[str, str] = {}
        self.idempotency: dict[tuple[str, str], ToolResult[Appointment]] = {}


def _fail[T](error: ToolError) -> ToolResult[T]:
    return ToolResult[T](ok=False, error=error)


def _ok[T](value: T) -> ToolResult[T]:
    return ToolResult[T](ok=True, value=value)


class FakeAppointmentCapability:
    """Contract-compliant fake. Not a production adapter: no network or SQL."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
        fault_plan: FaultPlan | None = None,
        initial_slots: Mapping[UUID, Sequence[AppointmentSlot]] | None = None,
    ) -> None:
        self._clock: Clock = clock or (lambda: datetime.now(tz=UTC))
        self._id_factory: IdFactory = id_factory or (lambda: str(uuid4()))
        self._fault_plan = fault_plan
        self._agendas: dict[UUID, _TenantAgenda] = {}
        for tenant_id, slots in (initial_slots or {}).items():
            agenda = _TenantAgenda()
            for slot in slots:
                agenda.slots[slot.slot_id] = slot
            self._agendas[tenant_id] = agenda

    def _agenda(self, tenant: TenantContext) -> _TenantAgenda:
        agenda = self._agendas.get(tenant.tenant_id)
        if agenda is None:
            agenda = _TenantAgenda()
            self._agendas[tenant.tenant_id] = agenda
        return agenda

    def _fault(self, operation: str) -> ToolError | None:
        plan = self._fault_plan
        if plan is None:
            return None
        if plan.operations is not None and operation not in plan.operations:
            return None
        if plan.fault == "timeout":
            return _TIMEOUT
        if plan.fault == "rate_limit":
            return _RATE_LIMITED
        return _MALFORMED

    def _replay(
        self, agenda: _TenantAgenda, operation: str, idempotency_key: str
    ) -> ToolResult[Appointment] | None:
        return agenda.idempotency.get((operation, idempotency_key))

    def _remember(
        self,
        agenda: _TenantAgenda,
        operation: str,
        idempotency_key: str,
        result: ToolResult[Appointment],
    ) -> ToolResult[Appointment]:
        agenda.idempotency[(operation, idempotency_key)] = result
        return result

    async def search(
        self,
        tenant: TenantContext,
        request: AppointmentSearchRequest,
    ) -> ToolResult[list[AppointmentSlot]]:
        fault = self._fault("search")
        if fault is not None:
            return _fail(fault)
        now = self._clock()
        booked = set(self._agenda(tenant).slot_of.values())
        matches: list[AppointmentSlot] = []
        for slot in self._agenda(tenant).slots.values():
            if slot.slot_id in booked:
                continue
            if slot.ends_at <= now:
                continue
            start_date = slot.starts_at.date()
            if start_date < request.date_from or start_date > request.date_to:
                continue
            if slot.specialty != request.specialty:
                continue
            if (
                request.practitioner is not None
                and slot.practitioner != request.practitioner
            ):
                continue
            if request.location is not None and slot.location != request.location:
                continue
            matches.append(slot)
        matches.sort(key=lambda item: item.starts_at)
        return _ok(matches)

    async def get(
        self,
        tenant: TenantContext,
        request: AppointmentGetRequest,
    ) -> ToolResult[Appointment]:
        fault = self._fault("get")
        if fault is not None:
            return _fail(fault)
        appointment = self._agenda(tenant).appointments.get(request.appointment_id)
        if appointment is None:
            return _fail(_NOT_FOUND)
        return _ok(appointment)

    async def create(
        self,
        tenant: TenantContext,
        request: AppointmentCreateRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]:
        fault = self._fault("create")
        if fault is not None:
            return _fail(fault)
        agenda = self._agenda(tenant)
        replayed = self._replay(agenda, "create", idempotency_key)
        if replayed is not None:
            return replayed
        slot = agenda.slots.get(request.slot_id)
        if slot is None or slot.ends_at <= self._clock():
            return self._remember(agenda, "create", idempotency_key, _fail(_NOT_FOUND))
        if request.slot_id in agenda.slot_of.values():
            return self._remember(agenda, "create", idempotency_key, _fail(_CONFLICT))
        appointment = Appointment(
            appointment_id=self._id_factory(),
            status=AppointmentStatus.SCHEDULED,
            starts_at=slot.starts_at,
            ends_at=slot.ends_at,
            specialty=slot.specialty,
            practitioner=slot.practitioner,
            location=slot.location,
        )
        agenda.appointments[appointment.appointment_id] = appointment
        agenda.slot_of[appointment.appointment_id] = request.slot_id
        return self._remember(agenda, "create", idempotency_key, _ok(appointment))

    async def cancel(
        self,
        tenant: TenantContext,
        request: AppointmentCancelRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]:
        fault = self._fault("cancel")
        if fault is not None:
            return _fail(fault)
        agenda = self._agenda(tenant)
        replayed = self._replay(agenda, "cancel", idempotency_key)
        if replayed is not None:
            return replayed
        current = agenda.appointments.get(request.appointment_id)
        if current is None:
            return self._remember(agenda, "cancel", idempotency_key, _fail(_NOT_FOUND))
        if current.status is AppointmentStatus.CANCELLED:
            return self._remember(agenda, "cancel", idempotency_key, _ok(current))
        updated = current.model_copy(update={"status": AppointmentStatus.CANCELLED})
        agenda.appointments[updated.appointment_id] = updated
        agenda.slot_of.pop(updated.appointment_id, None)
        return self._remember(agenda, "cancel", idempotency_key, _ok(updated))

    async def reschedule(
        self,
        tenant: TenantContext,
        request: AppointmentRescheduleRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]:
        fault = self._fault("reschedule")
        if fault is not None:
            return _fail(fault)
        agenda = self._agenda(tenant)
        replayed = self._replay(agenda, "reschedule", idempotency_key)
        if replayed is not None:
            return replayed
        current = agenda.appointments.get(request.appointment_id)
        if current is None:
            return self._remember(
                agenda, "reschedule", idempotency_key, _fail(_NOT_FOUND)
            )
        if current.status not in _ACTIVE_STATUSES:
            return self._remember(
                agenda, "reschedule", idempotency_key, _fail(_INVALID_TRANSITION)
            )
        new_slot = agenda.slots.get(request.new_slot_id)
        if new_slot is None or new_slot.ends_at <= self._clock():
            return self._remember(
                agenda, "reschedule", idempotency_key, _fail(_NOT_FOUND)
            )
        occupant = next(
            (
                appointment_id
                for appointment_id, slot_id in agenda.slot_of.items()
                if slot_id == request.new_slot_id
            ),
            None,
        )
        if occupant is not None and occupant != request.appointment_id:
            return self._remember(
                agenda, "reschedule", idempotency_key, _fail(_CONFLICT)
            )
        updated = current.model_copy(
            update={
                "status": AppointmentStatus.RESCHEDULED,
                "starts_at": new_slot.starts_at,
                "ends_at": new_slot.ends_at,
                "specialty": new_slot.specialty,
                "practitioner": new_slot.practitioner,
                "location": new_slot.location,
            }
        )
        agenda.appointments[updated.appointment_id] = updated
        agenda.slot_of[updated.appointment_id] = request.new_slot_id
        return self._remember(agenda, "reschedule", idempotency_key, _ok(updated))

    async def confirm(
        self,
        tenant: TenantContext,
        request: AppointmentConfirmRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]:
        fault = self._fault("confirm")
        if fault is not None:
            return _fail(fault)
        agenda = self._agenda(tenant)
        replayed = self._replay(agenda, "confirm", idempotency_key)
        if replayed is not None:
            return replayed
        current = agenda.appointments.get(request.appointment_id)
        if current is None:
            return self._remember(agenda, "confirm", idempotency_key, _fail(_NOT_FOUND))
        if current.status not in _CONFIRMABLE:
            return self._remember(
                agenda, "confirm", idempotency_key, _fail(_INVALID_TRANSITION)
            )
        if current.status is AppointmentStatus.CONFIRMED:
            return self._remember(agenda, "confirm", idempotency_key, _ok(current))
        updated = current.model_copy(update={"status": AppointmentStatus.CONFIRMED})
        agenda.appointments[updated.appointment_id] = updated
        return self._remember(agenda, "confirm", idempotency_key, _ok(updated))
