import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from ia_mcp.configuration.models import TenantConfig
from ia_mcp.contracts.appointments import (
    Appointment,
    AppointmentCancelRequest,
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

_LOOKUP_EVENTS = frozenset({"lookup", "get_appointment"})
_SENSITIVE = ("token", "secret", "password", "credential")
_SAFE_ERROR = "The request could not be completed."
_FORBIDDEN_MESSAGE = "Action is not allowed."
_TERMINAL = frozenset(
    {"completed", "failed", "manual_review_required", "cancelled"}
)
_REVIEW_CODES = frozenset(
    {ToolErrorCode.UPSTREAM_TIMEOUT, ToolErrorCode.CONTRACT_VIOLATION}
)


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


def _tool_error_code(result: Any) -> str:
    error = getattr(result, "error", None)
    code = getattr(error, "code", None)
    if code is None:
        return "failed"
    return str(code)


def _review_code(result: Any) -> str:
    error = getattr(result, "error", None)
    code = getattr(error, "code", None)
    if code in _REVIEW_CODES:
        return str(code)
    return "manual_review_required"


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


def _already_settled(execution: WorkflowExecution) -> bool:
    return execution.state in _TERMINAL


def _already_settled_result(result: WorkflowResult) -> bool:
    return result.state in _TERMINAL


def _appointment_id(data: Mapping[str, object]) -> str | None:
    value = data.get("appointment_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


class CancelAppointmentDefinition:
    def transition(self, from_state: str, event: str) -> WorkflowState:
        if from_state == "collecting" and event in _LOOKUP_EVENTS:
            return "collecting"
        return WorkflowDefinition().transition(from_state, event)

    async def start(
        self,
        engine: WorkflowEngine,
        tenant: TenantContext,
        *,
        command_id: str,
        config: TenantConfig,
        appointment_id: str,
        conversation_id: UUID | None = None,
        idempotency_key: str | None = None,
        run_id: UUID | None = None,
    ) -> WorkflowResult:
        del config
        return await engine.start(
            tenant,
            StartWorkflow(
                command_id=command_id,
                workflow_type="cancel_appointment",
                conversation_id=conversation_id,
                data={"phase": "collecting", "appointment_id": appointment_id},
                run_id=run_id,
                idempotency_key=idempotency_key,
            ),
        )

    async def lookup(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
        config: TenantConfig,
    ) -> WorkflowResult:
        if "appointments" not in config.enabled_skills:
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=command_id,
                    event_type="fail",
                    payload={
                        "error": _FORBIDDEN_MESSAGE,
                        "error_code": "forbidden",
                    },
                ),
            )
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
                    event_type="fail",
                    payload={
                        "error": "The requested resource was not found.",
                        "error_code": "not_found",
                    },
                ),
            )
        result = await executor.execute(
            tenant,
            run_id,
            ToolCall(
                name="appointments.get",
                arguments=AppointmentGetRequest(
                    appointment_id=appointment_id
                ).model_dump(exclude_none=True),
            ),
        )
        if not result.ok or not isinstance(result.value, Appointment):
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=command_id,
                    event_type="fail",
                    payload={
                        "error": _safe_error(result),
                        "error_code": _tool_error_code(result),
                    },
                ),
            )
        appointment = result.value
        payload = _public_mapping(appointment.model_dump(mode="json"))
        payload["appointment_id"] = appointment.appointment_id
        if appointment.status is AppointmentStatus.CANCELLED:
            payload["already_cancelled"] = True
        await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=f"{command_id}:get",
                event_type="lookup",
                payload=payload,
            ),
        )
        return await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=f"{command_id}:submit",
                event_type="submit",
                payload={**payload, "phase": "awaiting_confirmation"},
            ),
        )

    async def confirm_cancel(
        self,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        run_id: UUID,
        config: TenantConfig,
        confirmed: bool,
    ) -> WorkflowResult:
        del config
        execution = await engine._repository.get(tenant, workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        if _already_settled(execution):
            return _as_result(execution, command_id)
        if not confirmed:
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=command_id,
                    event_type="cancel",
                    payload={"phase": "cancelled"},
                ),
            )
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
            return await self._await_settled(
                engine, tenant, workflow_id, command_id
            )
        appointment_id = _appointment_id(claimed.data)
        if appointment_id is None:
            return await self._review(
                engine,
                tenant,
                workflow_id,
                command_id,
                error=_SAFE_ERROR,
            )
        result = await executor.execute(
            tenant,
            run_id,
            ToolCall(
                name="appointments.cancel",
                arguments=AppointmentCancelRequest(
                    appointment_id=appointment_id
                ).model_dump(exclude_none=True),
                idempotency_key=f"{workflow_id}:appointments.cancel",
            ),
        )
        if result.ok and isinstance(result.value, Appointment):
            appointment = result.value
            payload = _public_mapping(appointment.model_dump(mode="json"))
            payload["appointment_id"] = appointment.appointment_id
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
