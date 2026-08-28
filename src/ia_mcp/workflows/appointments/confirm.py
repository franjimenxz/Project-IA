import asyncio
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import SecretStr

from ia_mcp.contracts.appointments import (
    Appointment,
    AppointmentConfirmRequest,
    AppointmentGetRequest,
    AppointmentStatus,
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

_STAY_COLLECTING = frozenset({"load_appointment", "apply_reply"})
_SENSITIVE = ("token", "secret", "password", "credential")
_SAFE_CORRECTION = "Please correct the provided information."
_SAFE_CLARIFICATION = "Please confirm with a clear yes to continue."
_SAFE_ERROR = "The request could not be completed."
_TERMINAL = frozenset(
    {"completed", "failed", "manual_review_required", "cancelled"}
)
_REVIEW_CODES = frozenset(
    {ToolErrorCode.UPSTREAM_TIMEOUT, ToolErrorCode.CONTRACT_VIOLATION}
)
_CONFIRMABLE = frozenset(
    {
        AppointmentStatus.SCHEDULED,
        AppointmentStatus.PENDING_CONFIRMATION,
        AppointmentStatus.RESCHEDULED,
        AppointmentStatus.CONFIRMED,
    }
)
_AFFIRMATIVE = frozenset(
    {"yes", "si", "sí", "ok", "okay", "confirm", "confirmo", "dale"}
)


def _as_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _is_affirmative(text: str) -> bool:
    return text.strip().lower() in _AFFIRMATIVE


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


def _appointment_id(data: Mapping[str, object]) -> str | None:
    value = data.get("appointment_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _appointment_public(appointment: Appointment) -> dict[str, object]:
    dumped = appointment.model_dump(mode="json")
    payload = _public_mapping(dumped)
    starts = appointment.starts_at
    payload["date_from"] = starts.date().isoformat()
    payload["date_to"] = (starts.date() + timedelta(days=14)).isoformat()
    return payload


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


def _confirm_arguments(appointment_id: str) -> dict[str, object]:
    request = AppointmentConfirmRequest(appointment_id=appointment_id)
    return request.model_dump(exclude_none=True)


class ConfirmAppointmentDefinition:
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
                workflow_type="confirm_appointment",
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
        payload = _appointment_public(result.value)
        payload["phase"] = "appointment_loaded"
        payload["error"] = ""
        return await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=command_id,
                event_type="load_appointment",
                payload=payload,
            ),
        )

    async def apply_reply(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
        text: str,
    ) -> WorkflowResult:
        if _is_affirmative(text):
            return await self.confirm_appointment(
                engine,
                executor,
                tenant,
                workflow_id,
                command_id=command_id,
                run_id=run_id,
                reply=text,
            )
        execution = await engine._repository.get(tenant, workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        if _already_settled(execution):
            return _as_result(execution, command_id)
        return await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=command_id,
                event_type="apply_reply",
                payload={"phase": "collecting", "correction": _SAFE_CLARIFICATION},
            ),
        )

    async def confirm_appointment(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
        reply: str | None = None,
    ) -> WorkflowResult:
        execution = await engine._repository.get(tenant, workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        if _already_settled(execution):
            return _as_result(execution, command_id)
        decision: Literal["mutate", "already_confirmed"] | None = None
        snapshot: Appointment | None = None
        if execution.state == "collecting":
            outcome = await self._preflight(
                engine,
                executor,
                tenant,
                workflow_id,
                execution,
                command_id=command_id,
                run_id=run_id,
                reply=reply,
            )
            if outcome is None:
                loaded = await engine._repository.get(tenant, workflow_id)
                if loaded is None:
                    raise WorkflowError("not_found", "Resource not found")
                return _as_result(loaded, command_id)
            decision, snapshot = outcome
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
        if snapshot is None:
            return await self._review(
                engine,
                tenant,
                workflow_id,
                command_id,
                error=_SAFE_ERROR,
            )
        if decision == "already_confirmed":
            return await self._succeed(
                engine, tenant, workflow_id, command_id, snapshot
            )
        return await self._confirm_and_finish(
            engine,
            executor,
            tenant,
            workflow_id,
            command_id=command_id,
            run_id=run_id,
            appointment_id=snapshot.appointment_id,
        )

    async def _preflight(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        execution: WorkflowExecution,
        *,
        command_id: str,
        run_id: UUID,
        reply: str | None,
    ) -> tuple[Literal["mutate", "already_confirmed"], Appointment] | None:
        if reply is not None and not _is_affirmative(reply):
            await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:reply",
                    event_type="apply_reply",
                    payload={
                        "phase": "collecting",
                        "correction": _SAFE_CLARIFICATION,
                    },
                ),
            )
            return None
        appointment_id = _appointment_id(execution.data)
        if appointment_id is None:
            await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:preflight",
                    event_type="load_appointment",
                    payload={"phase": "collecting", "correction": _SAFE_CORRECTION},
                ),
            )
            return None
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
            await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:preflight",
                    event_type="load_appointment",
                    payload={"phase": "collecting", "error": _safe_error(result)},
                ),
            )
            return None
        appointment = result.value
        if appointment.status is AppointmentStatus.CONFIRMED:
            return ("already_confirmed", appointment)
        if appointment.status not in _CONFIRMABLE:
            await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=f"{command_id}:preflight",
                    event_type="load_appointment",
                    payload={"phase": "collecting", "error": _SAFE_ERROR},
                ),
            )
            return None
        return ("mutate", appointment)

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

    async def _confirm_and_finish(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
        appointment_id: str,
    ) -> WorkflowResult:
        result = await executor.execute(
            tenant,
            run_id,
            ToolCall(
                name="appointments.confirm",
                arguments=_confirm_arguments(appointment_id),
                idempotency_key=f"{workflow_id}:appointments.confirm",
            ),
        )
        if result.ok and isinstance(result.value, Appointment):
            return await self._succeed(
                engine, tenant, workflow_id, command_id, result.value
            )
        return await self._review(
            engine,
            tenant,
            workflow_id,
            command_id,
            error=_safe_error(result),
            error_code=_review_code(result),
        )

    async def _succeed(
        self,
        engine: WorkflowEngine,
        tenant: TenantContext,
        workflow_id: UUID,
        command_id: str,
        appointment: Appointment,
    ) -> WorkflowResult:
        payload = _appointment_public(appointment)
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
