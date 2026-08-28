from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.models import (
    AdvanceCommand,
    OutboxEvent,
    StartWorkflow,
    WorkflowExecution,
    WorkflowResult,
    WorkflowState,
    WorkflowTransition,
    sanitize_payload,
    status_for,
)
from ia_mcp.workflows.ports import WorkflowDefinition, WorkflowError, WorkflowRepository


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_key(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _error_for(state: WorkflowState, payload: dict[str, object]) -> str | None:
    if state not in {"failed", "manual_review_required"}:
        return None
    code = payload.get("error_code")
    if isinstance(code, str) and code:
        return code
    return state


def _to_result(
    execution: WorkflowExecution, transition: WorkflowTransition
) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=execution.id,
        command_id=transition.command_id,
        type=execution.type,
        schema_version=execution.schema_version,
        state=transition.to_state,
        status=status_for(transition.to_state),
        lock_version=transition.sequence,
        data=dict(execution.data),
        error=execution.error,
    )


class WorkflowEngine:
    def __init__(
        self, repository: WorkflowRepository, definition: WorkflowDefinition
    ) -> None:
        self._repository = repository
        self._definition = definition

    async def start(self, tenant: TenantContext, command: StartWorkflow) -> WorkflowResult:
        key_hash = (
            _hash_key(command.idempotency_key) if command.idempotency_key else None
        )
        if key_hash is not None:
            existing = await self._repository.get_by_idempotency(tenant, key_hash)
            if existing is not None:
                return await self._result_for_command(
                    tenant, existing.id, command.command_id, fallback=existing
                )
        now = _now()
        workflow_id = uuid4()
        data = sanitize_payload(command.data)
        execution = WorkflowExecution(
            tenant_id=tenant.tenant_id,
            id=workflow_id,
            conversation_id=command.conversation_id,
            type=command.workflow_type,
            schema_version=command.schema_version,
            state="collecting",
            status="running",
            data=data,
            idempotency_key_hash=key_hash,
            lock_version=1,
            created_at=now,
            updated_at=now,
            error=None,
        )
        transition = WorkflowTransition(
            tenant_id=tenant.tenant_id,
            workflow_id=workflow_id,
            sequence=1,
            from_state=None,
            to_state="collecting",
            command_id=command.command_id,
            event_type="start",
            payload=data,
            actor=command.actor,
            run_id=command.run_id,
            timestamp=now,
        )
        outbox = OutboxEvent(
            tenant_id=tenant.tenant_id,
            id=uuid4(),
            kind="workflow.started",
            payload={
                "workflow_id": str(workflow_id),
                "command_id": command.command_id,
                "from_state": None,
                "to_state": "collecting",
                "event_type": "start",
                "data": data,
            },
            created_at=now,
        )
        try:
            await self._repository.create(tenant, execution, transition, outbox)
        except WorkflowError as exc:
            if key_hash is not None and exc.code == "conflict":
                existing = await self._repository.get_by_idempotency(tenant, key_hash)
                if existing is not None:
                    return await self._result_for_command(
                        tenant, existing.id, command.command_id, fallback=existing
                    )
            raise
        return _to_result(execution, transition)

    async def advance(
        self, tenant: TenantContext, command: AdvanceCommand
    ) -> WorkflowResult:
        recorded = await self._repository.get_transition(
            tenant, command.workflow_id, command.command_id
        )
        if recorded is not None:
            return await self._result_for_transition(tenant, recorded)
        execution = await self._repository.get(tenant, command.workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        to_state = self._definition.transition(execution.state, command.event_type)
        now = _now()
        payload = sanitize_payload(command.payload)
        lock_version = execution.lock_version + 1
        updated = WorkflowExecution(
            tenant_id=execution.tenant_id,
            id=execution.id,
            conversation_id=execution.conversation_id,
            type=execution.type,
            schema_version=execution.schema_version,
            state=to_state,
            status=status_for(to_state),
            data={**dict(execution.data), **payload},
            idempotency_key_hash=execution.idempotency_key_hash,
            lock_version=lock_version,
            created_at=execution.created_at,
            updated_at=now,
            error=_error_for(to_state, payload),
        )
        transition = WorkflowTransition(
            tenant_id=execution.tenant_id,
            workflow_id=execution.id,
            sequence=lock_version,
            from_state=execution.state,
            to_state=to_state,
            command_id=command.command_id,
            event_type=command.event_type,
            payload=payload,
            actor=command.actor,
            run_id=command.run_id,
            timestamp=now,
        )
        outbox = OutboxEvent(
            tenant_id=execution.tenant_id,
            id=uuid4(),
            kind="workflow.transitioned",
            payload={
                "workflow_id": str(execution.id),
                "command_id": command.command_id,
                "from_state": execution.state,
                "to_state": to_state,
                "event_type": command.event_type,
                "data": payload,
            },
            created_at=now,
        )
        try:
            stored = await self._repository.cas_advance(
                tenant,
                execution.lock_version,
                updated,
                transition,
                outbox,
            )
        except WorkflowError as exc:
            if exc.code in {"conflict", "not_found"}:
                replayed = await self._repository.get_transition(
                    tenant, command.workflow_id, command.command_id
                )
                if replayed is not None:
                    return await self._result_for_transition(tenant, replayed)
            raise
        return _to_result(stored, transition)

    async def _result_for_transition(
        self, tenant: TenantContext, transition: WorkflowTransition
    ) -> WorkflowResult:
        execution = await self._repository.get(tenant, transition.workflow_id)
        if execution is None:
            raise WorkflowError("not_found", "Resource not found")
        return _to_result(execution, transition)

    async def _result_for_command(
        self,
        tenant: TenantContext,
        workflow_id: UUID,
        command_id: str,
        *,
        fallback: WorkflowExecution,
    ) -> WorkflowResult:
        transition = await self._repository.get_transition(
            tenant, workflow_id, command_id
        )
        if transition is not None:
            return _to_result(fallback, transition)
        transitions = await self._repository.list_transitions(tenant, workflow_id)
        if not transitions:
            raise WorkflowError("not_found", "Resource not found")
        return _to_result(fallback, transitions[0])
