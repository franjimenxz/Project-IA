from uuid import uuid4

from ia_mcp.mcp.executor import ToolExecutor
from ia_mcp.scheduling.models import JOB_TYPE
from ia_mcp.scheduling.ports import JobStore
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.appointments.confirm import ConfirmAppointmentDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import WorkflowResult


class ConfirmationIngress:
    def __init__(
        self,
        store: JobStore,
        engine: WorkflowEngine,
        executor: ToolExecutor,
        *,
        definition: ConfirmAppointmentDefinition | None = None,
    ) -> None:
        self._store = store
        self._engine = engine
        self._executor = executor
        self._definition = definition or ConfirmAppointmentDefinition()

    async def apply_reply(
        self,
        tenant: TenantContext,
        *,
        appointment_id: str,
        text: str,
        command_id: str,
    ) -> WorkflowResult:
        job = await self._store.get_by_identity(
            tenant, JOB_TYPE, f"{appointment_id}:pre_appointment"
        )
        if job is None or job.status != "dispatched":
            raise LookupError("reminder_not_dispatched")
        started = await self._definition.start(
            self._engine,
            tenant,
            command_id=f"{command_id}:start",
            appointment_id=appointment_id,
        )
        await self._definition.load_appointment(
            self._engine,
            self._executor,
            tenant,
            started.workflow_id,
            command_id=f"{command_id}:load",
            run_id=uuid4(),
        )
        return await self._definition.apply_reply(
            self._engine,
            self._executor,
            tenant,
            started.workflow_id,
            command_id=command_id,
            run_id=uuid4(),
            text=text,
        )
