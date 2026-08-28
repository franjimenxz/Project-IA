import asyncio
from uuid import UUID

from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.models import OutboxEvent, WorkflowExecution, WorkflowTransition
from ia_mcp.workflows.ports import WorkflowError


class InMemoryWorkflowRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._executions: dict[tuple[UUID, UUID], WorkflowExecution] = {}
        self._transitions: list[WorkflowTransition] = []
        self._outbox: list[OutboxEvent] = []

    async def create(
        self,
        tenant: TenantContext,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> None:
        async with self._lock:
            if execution.tenant_id != tenant.tenant_id:
                raise WorkflowError("not_found", "Resource not found")
            if execution.idempotency_key_hash is not None:
                for stored in self._executions.values():
                    if (
                        stored.tenant_id == tenant.tenant_id
                        and stored.idempotency_key_hash
                        == execution.idempotency_key_hash
                    ):
                        raise WorkflowError(
                            "conflict", "Workflow was updated concurrently."
                        )
            key = (tenant.tenant_id, execution.id)
            if key in self._executions:
                raise WorkflowError("conflict", "Workflow was updated concurrently.")
            self._executions[key] = execution
            self._transitions.append(transition)
            self._outbox.append(outbox)

    async def get(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> WorkflowExecution | None:
        async with self._lock:
            return self._executions.get((tenant.tenant_id, workflow_id))

    async def get_by_idempotency(
        self, tenant: TenantContext, idempotency_key_hash: str
    ) -> WorkflowExecution | None:
        async with self._lock:
            for execution in self._executions.values():
                if (
                    execution.tenant_id == tenant.tenant_id
                    and execution.idempotency_key_hash == idempotency_key_hash
                ):
                    return execution
            return None

    async def get_transition(
        self, tenant: TenantContext, workflow_id: UUID, command_id: str
    ) -> WorkflowTransition | None:
        async with self._lock:
            for transition in self._transitions:
                if (
                    transition.tenant_id == tenant.tenant_id
                    and transition.workflow_id == workflow_id
                    and transition.command_id == command_id
                ):
                    return transition
            return None

    async def list_transitions(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> tuple[WorkflowTransition, ...]:
        async with self._lock:
            matches = [
                transition
                for transition in self._transitions
                if transition.tenant_id == tenant.tenant_id
                and transition.workflow_id == workflow_id
            ]
            return tuple(sorted(matches, key=lambda item: item.sequence))

    async def count_transitions(
        self,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str | None = None,
    ) -> int:
        async with self._lock:
            total = 0
            for transition in self._transitions:
                if transition.tenant_id != tenant.tenant_id:
                    continue
                if transition.workflow_id != workflow_id:
                    continue
                if command_id is not None and transition.command_id != command_id:
                    continue
                total += 1
            return total

    async def cas_advance(
        self,
        tenant: TenantContext,
        expected_lock_version: int,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> WorkflowExecution:
        async with self._lock:
            if execution.tenant_id != tenant.tenant_id:
                raise WorkflowError("not_found", "Resource not found")
            key = (tenant.tenant_id, execution.id)
            current = self._executions.get(key)
            if current is None:
                raise WorkflowError("not_found", "Resource not found")
            for existing in self._transitions:
                if (
                    existing.tenant_id == tenant.tenant_id
                    and existing.workflow_id == execution.id
                    and existing.command_id == transition.command_id
                ):
                    raise WorkflowError(
                        "conflict", "Workflow was updated concurrently."
                    )
            if current.lock_version != expected_lock_version:
                raise WorkflowError(
                    "conflict", "Workflow was updated concurrently."
                )
            self._executions[key] = execution
            self._transitions.append(transition)
            self._outbox.append(outbox)
            return execution
