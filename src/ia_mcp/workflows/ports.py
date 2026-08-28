from typing import Protocol
from uuid import UUID

from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.models import (
    OutboxEvent,
    WorkflowExecution,
    WorkflowState,
    WorkflowTransition,
)


class WorkflowError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


class WorkflowDefinition(Protocol):
    def transition(self, from_state: str, event: str) -> WorkflowState: ...


class WorkflowRepository(Protocol):
    async def create(
        self,
        tenant: TenantContext,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> None: ...

    async def get(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> WorkflowExecution | None: ...

    async def get_by_idempotency(
        self, tenant: TenantContext, idempotency_key_hash: str
    ) -> WorkflowExecution | None: ...

    async def get_transition(
        self, tenant: TenantContext, workflow_id: UUID, command_id: str
    ) -> WorkflowTransition | None: ...

    async def list_transitions(
        self, tenant: TenantContext, workflow_id: UUID
    ) -> tuple[WorkflowTransition, ...]: ...

    async def count_transitions(
        self,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str | None = None,
    ) -> int: ...

    async def cas_advance(
        self,
        tenant: TenantContext,
        expected_lock_version: int,
        execution: WorkflowExecution,
        transition: WorkflowTransition,
        outbox: OutboxEvent,
    ) -> WorkflowExecution: ...
