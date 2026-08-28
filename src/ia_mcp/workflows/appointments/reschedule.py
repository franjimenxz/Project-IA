import asyncio
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from ia_mcp.contracts.appointments import (
    Appointment,
    AppointmentGetRequest,
    AppointmentRescheduleRequest,
    AppointmentSearchRequest,
    AppointmentSlot,
)
from ia_mcp.contracts.errors import ToolErrorCode
from ia_mcp.mcp.executor import ToolCall, ToolExecutor
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.definition import WorkflowDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import (
    AdvanceCommand,
    StartWorkflow,
    WorkflowExecution,
    WorkflowResult,
    WorkflowState,
    status_for,
)
from ia_mcp.workflows.ports import WorkflowError

_STAY_COLLECTING = frozenset(
    {"load_appointment", "search_slots", "present_slots", "select_slot"}
)
_SENSITIVE = ("token", "secret", "password", "credential")
_SAFE_CORRECTION = "Please correct the provided information."
_SAFE_ERROR = "The request could not be completed."
_TERMINAL = frozenset(
    {"completed", "failed", "manual_review_required", "cancelled"}
)
_REVIEW_CODES = frozenset(
    {ToolErrorCode.UPSTREAM_TIMEOUT, ToolErrorCode.CONTRACT_VIOLATION}
)


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _as_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _public_mapping(payload: Mapping[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in _SENSITIVE):
            continue
        if isinstance(value, SecretStr):
            continue
        cleaned[key] = value
    return cleaned


def _safe_error(result: Any) -> str:
    error = getattr(result, "error", None)
    message = getattr(error, "safe_message", None)
    if isinstance(message, str) and message:
        return message
    return _SAFE_ERROR


def _as_result(execution: WorkflowExecution, command_id: str) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=execution.id,
        command_id=command_id,
        type=execution.type,
        schema_version=execution.schema_version,
        state=execution.state,
        status=status_for(execution.state),
        lock_version=execution.lock_version,
        data=dict(execution.data),
        error=execution.error,
    )


def _selected_slot(data: Mapping[str, object]) -> str | None:
    value = data.get("selected_slot")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _appointment_id(data: Mapping[str, object]) -> str | None:
    value = data.get("appointment_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _live_slot(slots: Sequence[object], slot_id: str) -> AppointmentSlot | None:
    for slot in slots:
        if isinstance(slot, AppointmentSlot) and slot.slot_id == slot_id:
            return slot
    return None


def _has_search_fields(data: Mapping[str, object]) -> bool:
    return (
        _as_text(data.get("specialty")) is not None
        and _as_date(data.get("date_from")) is not None
        and _as_date(data.get("date_to")) is not None
    )


def _search_arguments(data: Mapping[str, object]) -> dict[str, object]:
    specialty = _as_text(data.get("specialty"))
    date_from = _as_date(data.get("date_from"))
    date_to = _as_date(data.get("date_to"))
    if specialty is None or date_from is None or date_to is None:
        raise WorkflowError("invalid_transition", _SAFE_CORRECTION)
    request = AppointmentSearchRequest(
        specialty=specialty, date_from=date_from, date_to=date_to
    )
    return request.model_dump(mode="json", exclude_none=True)


def _reschedule_arguments(
    appointment_id: str, slot: AppointmentSlot
) -> dict[str, object]:
    request = AppointmentRescheduleRequest(
        appointment_id=appointment_id,
        new_slot_id=slot.slot_id,
        booking_token=slot.booking_token,
    )
    return request.model_dump(exclude_none=True)


def _appointment_public(appointment: Appointment) -> dict[str, object]:
    dumped = appointment.model_dump(mode="json")
    return _public_mapping(dumped)


def _already_settled(execution: WorkflowExecution) -> bool:
    return execution.state in _TERMINAL


def _already_settled_result(result: WorkflowResult) -> bool:
    return result.state in _TERMINAL


def _review_code(result: Any) -> str:
    error = getattr(result, "error", None)
    code = getattr(error, "code", None)
    if code in _REVIEW_CODES:
        return str(code)
    return "manual_review_required"


class RescheduleAppointmentDefinition:
    def transition(self, from_state: str, event: str) -> WorkflowState:
        if from_state == "collecting" and event in _STAY_COLLECTING:
            return "collecting"
        return WorkflowDefinition().transition(from_state, event)

    async def start(
        self,
        engine: WorkflowEngine,
        tenant: TenantContext,
        *,
        command_id: str,
        appointment_id: str,
        conversation_id: UUID | None = None,
        idempotency_key: str | None = None,
        run_id: UUID | None = None,
    ) -> WorkflowResult:
        return await engine.start(
            tenant,
            StartWorkflow(
                command_id=command_id,
                workflow_type="reschedule_appointment",
                conversation_id=conversation_id,
                data={"phase": "collecting", "appointment_id": appointment_id},
                run_id=run_id,
                idempotency_key=idempotency_key,
            ),
        )

    async def load_appointment(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
    ) -> WorkflowResult:
        execution = await engine._repository.get(tenant, workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        appointment_id = _appointment_id(execution.data)
        if appointment_id is None:
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=command_id,
                    event_type="load_appointment",
                    payload={"phase": "collecting", "correction": _SAFE_CORRECTION},
                ),
            )
        result = await executor.execute(
            tenant,
            run_id,
            ToolCall(
                name="appointments.get",
                arguments=AppointmentGetRequest(
                    appointment_id=appointment_id
                ).model_dump(mode="json"),
            ),
        )
        if not result.ok or not isinstance(result.value, Appointment):
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=command_id,
                    event_type="load_appointment",
                    payload={"phase": "collecting", "error": _safe_error(result)},
                ),
            )
        appointment = result.value
        payload = _appointment_public(appointment)
        starts = appointment.starts_at
        payload["phase"] = "appointment_loaded"
        payload["error"] = ""
        payload["date_from"] = starts.date().isoformat()
        payload["date_to"] = (starts.date() + timedelta(days=14)).isoformat()
        return await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=command_id,
                event_type="load_appointment",
                payload=payload,
            ),
        )

    async def search_slots(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
    ) -> WorkflowResult:
        execution = await engine._repository.get(tenant, workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        if not _has_search_fields(execution.data):
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=command_id,
                    event_type="search_slots",
                    payload={"phase": "collecting", "correction": _SAFE_CORRECTION},
                ),
            )
        await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=command_id,
                event_type="search_slots",
                payload={"phase": "searching_slots"},
            ),
        )
        result = await executor.execute(
            tenant,
            run_id,
            ToolCall(
                name="appointments.search",
                arguments=_search_arguments(execution.data),
            ),
        )
        outcome_id = f"{command_id}:outcome"
        if result.ok:
            value = result.value
            slots_in: Sequence[object] = value if isinstance(value, list) else []
            slots = self.present_slots(slots_in)
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=outcome_id,
                    event_type="present_slots",
                    payload={
                        "phase": "awaiting_slot_selection",
                        "slots": slots,
                        "error": "",
                    },
                ),
            )
        return await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=outcome_id,
                event_type="search_slots",
                payload={"phase": "searching_slots", "error": _safe_error(result)},
            ),
        )

    def present_slots(self, slots: Sequence[object]) -> list[dict[str, object]]:
        presented: list[dict[str, object]] = []
        for slot in slots:
            dumped: Mapping[str, object]
            if isinstance(slot, AppointmentSlot):
                dumped = slot.model_dump(mode="json", exclude={"booking_token"})
            elif isinstance(slot, Mapping):
                dumped = {
                    str(key): value
                    for key, value in slot.items()
                    if str(key) != "booking_token"
                }
            else:
                continue
            presented.append(_public_mapping(dumped))
        return presented

    async def select_slot(
        self,
        engine: WorkflowEngine,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        slot_id: str,
    ) -> WorkflowResult:
        return await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=command_id,
                event_type="select_slot",
                payload={
                    "phase": "awaiting_slot_selection",
                    "selected_slot": slot_id,
                },
            ),
        )

    async def apply_reschedule(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
    ) -> WorkflowResult:
        return await self.confirm_reschedule(
            engine,
            executor,
            tenant,
            workflow_id,
            command_id=command_id,
            run_id=run_id,
        )

    async def confirm_reschedule(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
    ) -> WorkflowResult:
        execution = await engine._repository.get(tenant, workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        if _already_settled(execution):
            return _as_result(execution, command_id)
        live_slot: AppointmentSlot | None = None
        if execution.state == "collecting":
            live_slot = await self._revalidate_slot(
                engine,
                executor,
                tenant,
                workflow_id,
                execution,
                command_id=command_id,
                run_id=run_id,
            )
            if live_slot is None:
                loaded = await engine._repository.get(tenant, workflow_id)
                if loaded is None:
                    raise WorkflowError("not_found", "Resource not found")
                return _as_result(loaded, command_id)
        try:
            claimed = await self._claim_executing(
                engine, tenant, workflow_id, command_id
            )
        except WorkflowError as exc:
            if exc.code in {"conflict", "invalid_transition"}:
                return await self._await_settled(
                    engine, tenant, workflow_id, command_id
                )
            raise
        if _already_settled_result(claimed):
            return claimed
        if claimed.state != "executing":
            return await self._await_settled(engine, tenant, workflow_id, command_id)
        if live_slot is None:
            return await self._review(
                engine,
                tenant,
                workflow_id,
                command_id,
                error=_SAFE_ERROR,
            )
        return await self._reschedule_and_finish(
            engine,
            executor,
            tenant,
            workflow_id,
            command_id=command_id,
            run_id=run_id,
            live_slot=live_slot,
            appointment_id=_appointment_id(execution.data) or "",
        )

    async def _revalidate_slot(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        execution: WorkflowExecution,
        *,
        command_id: str,
        run_id: UUID,
    ) -> AppointmentSlot | None:
        slot_id = _selected_slot(execution.data)
        if slot_id is None or not _has_search_fields(execution.data):
            await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:revalidate",
                    event_type="search_slots",
                    payload={
                        "phase": "awaiting_slot_selection",
                        "correction": _SAFE_CORRECTION,
                    },
                ),
            )
            return None
        result = await executor.execute(
            tenant,
            run_id,
            ToolCall(
                name="appointments.search",
                arguments=_search_arguments(execution.data),
            ),
        )
        if not result.ok:
            await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:revalidate",
                    event_type="search_slots",
                    payload={
                        "phase": "awaiting_slot_selection",
                        "error": _safe_error(result),
                    },
                ),
            )
            return None
        value = result.value
        slots_in: Sequence[object] = value if isinstance(value, list) else []
        live = _live_slot(slots_in, slot_id)
        if live is None:
            await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:revalidate",
                    event_type="present_slots",
                    payload={
                        "phase": "awaiting_slot_selection",
                        "slots": self.present_slots(slots_in),
                        "error": "",
                        "selected_slot": "",
                    },
                ),
            )
            return None
        return live

    async def _claim_executing(
        self,
        engine: WorkflowEngine,
        tenant: TenantContext,
        workflow_id: UUID,
        command_id: str,
    ) -> WorkflowResult:
        execution = await engine._repository.get(tenant, workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        if _already_settled(execution):
            return _as_result(execution, command_id)
        current = execution.state
        if current == "collecting":
            submitted = await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:submit",
                    event_type="submit",
                    payload={"phase": "awaiting_confirmation"},
                ),
            )
            current = submitted.state
            if _already_settled_result(submitted):
                return submitted
        if current == "awaiting_confirmation":
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:confirm",
                    event_type="confirm",
                    payload={"phase": "executing"},
                ),
            )
        raise WorkflowError("conflict", "Workflow was updated concurrently.")

    async def _reschedule_and_finish(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
        live_slot: AppointmentSlot,
        appointment_id: str,
    ) -> WorkflowResult:
        result = await executor.execute(
            tenant,
            run_id,
            ToolCall(
                name="appointments.reschedule",
                arguments=_reschedule_arguments(appointment_id, live_slot),
                idempotency_key=f"{workflow_id}:appointments.reschedule",
            ),
        )
        if result.ok and isinstance(result.value, Appointment):
            payload = _appointment_public(result.value)
            payload["phase"] = "completed"
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:succeed",
                    event_type="succeed",
                    payload=payload,
                ),
            )
        return await self._review(
            engine,
            tenant,
            workflow_id,
            command_id,
            error=_safe_error(result),
            error_code=_review_code(result),
        )

    async def _review(
        self,
        engine: WorkflowEngine,
        tenant: TenantContext,
        workflow_id: UUID,
        command_id: str,
        *,
        error: str,
        error_code: str = "manual_review_required",
    ) -> WorkflowResult:
        return await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=f"{command_id}:review",
                event_type="review",
                payload={"error": error, "error_code": error_code},
            ),
        )

    async def _await_settled(
        self,
        engine: WorkflowEngine,
        tenant: TenantContext,
        workflow_id: UUID,
        command_id: str,
    ) -> WorkflowResult:
        last: WorkflowExecution | None = None
        for _ in range(200):
            last = await engine._repository.get(tenant, workflow_id)
            if last is None:
                raise WorkflowError("not_found", "Resource not found")
            if _already_settled(last):
                return _as_result(last, command_id)
            await asyncio.sleep(0.01)
        if last is None:
            raise WorkflowError("not_found", "Resource not found")
        return _as_result(last, command_id)
