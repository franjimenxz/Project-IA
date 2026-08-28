from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from ia_mcp.configuration.models import TenantConfig
from ia_mcp.contracts.appointments import AppointmentSearchRequest, AppointmentSlot
from ia_mcp.mcp.executor import ToolCall, ToolExecutor
from ia_mcp.skills.base import FieldSpec
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.definition import WorkflowDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import (
    AdvanceCommand,
    StartWorkflow,
    WorkflowResult,
    WorkflowState,
)
from ia_mcp.workflows.ports import WorkflowError

_T07_EVENTS = frozenset({"collect_fields", "search_slots", "present_slots"})
_DATE_FIELDS = frozenset({"date_from", "date_to"})
_SEARCH_FIELDS = (
    "specialty",
    "date_from",
    "date_to",
    "practitioner",
    "location",
    "coverage",
)
_SENSITIVE = ("token", "secret", "password", "credential")
_SAFE_CORRECTION = "Please correct the provided information."
_SAFE_ERROR = "The request could not be completed."


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


def _validate_fields(fields: Mapping[str, object], config: TenantConfig) -> str | None:
    parsed_dates: dict[str, date] = {}
    for name in config.appointments.required_fields:
        value = fields.get(name)
        if name in _DATE_FIELDS:
            parsed = _as_date(value)
            if parsed is None:
                return _SAFE_CORRECTION
            parsed_dates[name] = parsed
            continue
        if _as_text(value) is None:
            return _SAFE_CORRECTION
    if (
        "date_from" in parsed_dates
        and "date_to" in parsed_dates
        and parsed_dates["date_from"] > parsed_dates["date_to"]
    ):
        return _SAFE_CORRECTION
    return None


def _normalized_fields(
    fields: Mapping[str, object], config: TenantConfig
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for name in config.appointments.required_fields:
        value = fields.get(name)
        if name in _DATE_FIELDS:
            parsed = _as_date(value)
            payload[name] = parsed.isoformat() if parsed is not None else value
        else:
            text = _as_text(value)
            payload[name] = text if text is not None else value
    return payload


def _search_arguments(
    data: Mapping[str, object], config: TenantConfig
) -> dict[str, object]:
    required = frozenset(config.appointments.required_fields)
    payload: dict[str, object] = {}
    for name in _SEARCH_FIELDS:
        if name not in required:
            continue
        value = data.get(name)
        if value in (None, ""):
            continue
        payload[name] = value
    request = AppointmentSearchRequest.model_validate(payload)
    return request.model_dump(mode="json", exclude_none=True)


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


class CreateAppointmentDefinition:
    def transition(self, from_state: str, event: str) -> WorkflowState:
        if from_state == "collecting" and event in _T07_EVENTS:
            return "collecting"
        return WorkflowDefinition().transition(from_state, event)

    def requested_fields(self, config: TenantConfig) -> tuple[FieldSpec, ...]:
        return tuple(
            FieldSpec(name=name, required=True)
            for name in config.appointments.required_fields
        )

    async def start(
        self,
        engine: WorkflowEngine,
        tenant: TenantContext,
        *,
        command_id: str,
        config: TenantConfig,
        conversation_id: UUID | None = None,
        idempotency_key: str | None = None,
        run_id: UUID | None = None,
    ) -> WorkflowResult:
        del config
        return await engine.start(
            tenant,
            StartWorkflow(
                command_id=command_id,
                workflow_type="create_appointment",
                conversation_id=conversation_id,
                data={"phase": "collecting_fields"},
                run_id=run_id,
                idempotency_key=idempotency_key,
            ),
        )

    async def collect_fields(
        self,
        engine: WorkflowEngine,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str,
        fields: Mapping[str, object],
        config: TenantConfig,
    ) -> WorkflowResult:
        correction = _validate_fields(fields, config)
        payload: dict[str, object] = {"phase": "collecting_fields"}
        if correction is not None:
            payload["correction"] = correction
        else:
            payload.update(_normalized_fields(fields, config))
            payload["correction"] = ""
        return await engine.advance(
            tenant,
            AdvanceCommand(
                workflow_id=workflow_id,
                command_id=command_id,
                event_type="collect_fields",
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
        config: TenantConfig,
    ) -> WorkflowResult:
        execution = await engine._repository.get(tenant, workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        correction = _validate_fields(execution.data, config)
        if correction is not None:
            return await engine.advance(
                tenant,
                AdvanceCommand(
                    workflow_id=workflow_id,
                    command_id=command_id,
                    event_type="search_slots",
                    payload={"phase": "collecting_fields", "correction": correction},
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
                arguments=_search_arguments(execution.data, config),
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
