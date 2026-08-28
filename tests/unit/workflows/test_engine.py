from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.definition import WorkflowDefinition
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import AdvanceCommand, StartWorkflow
from ia_mcp.workflows.ports import WorkflowError
from tests.unit.workflows.fakes import InMemoryWorkflowRepository

TENANT_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TENANT_A_CTX = TenantContext(
    tenant_id=TENANT_A,
    tenant_slug="tenant-a",
    config_version=1,
    correlation_id=UUID("33333333-3333-3333-3333-333333333333"),
)
TENANT_B_CTX = TenantContext(
    tenant_id=TENANT_B,
    tenant_slug="tenant-b",
    config_version=1,
    correlation_id=UUID("44444444-4444-4444-4444-444444444444"),
)


@dataclass(slots=True)
class Harness:
    engine: WorkflowEngine
    repository: InMemoryWorkflowRepository
    workflow_id: UUID


class _Transitions:
    def __init__(self, repository: InMemoryWorkflowRepository, workflow_id: UUID) -> None:
        self._repository = repository
        self._workflow_id = workflow_id

    async def count(self, command_id: str) -> int:
        return await self._repository.count_transitions(
            TENANT_A_CTX, self._workflow_id, command_id=command_id
        )


@pytest.fixture
async def harness() -> Harness:
    repository = InMemoryWorkflowRepository()
    engine = WorkflowEngine(repository, WorkflowDefinition())
    started = await engine.start(
        TENANT_A_CTX,
        StartWorkflow(command_id="start-1", workflow_type="generic", schema_version=1),
    )
    return Harness(engine, repository, started.workflow_id)


@pytest.fixture
def engine(harness: Harness) -> WorkflowEngine:
    return harness.engine


@pytest.fixture
def transitions(harness: Harness) -> _Transitions:
    return _Transitions(harness.repository, harness.workflow_id)


@pytest.fixture
def command(harness: Harness) -> Callable[..., AdvanceCommand]:
    workflow_id = harness.workflow_id

    def _command(*, id: str, event_type: str = "submit") -> AdvanceCommand:
        return AdvanceCommand(
            workflow_id=workflow_id, command_id=id, event_type=event_type
        )

    return _command


@pytest.mark.anyio
async def test_duplicate_command_returns_recorded_transition(
    engine: WorkflowEngine,
    command: Callable[..., AdvanceCommand],
    transitions: _Transitions,
) -> None:
    first = await engine.advance(TENANT_A_CTX, command(id="cmd-1"))
    second = await engine.advance(TENANT_A_CTX, command(id="cmd-1"))
    assert second == first
    assert await transitions.count(command_id="cmd-1") == 1


@pytest.mark.anyio
async def test_invalid_transition_does_not_mutate_state(
    harness: Harness, command: Callable[..., AdvanceCommand]
) -> None:
    with pytest.raises(WorkflowError) as caught:
        await harness.engine.advance(
            TENANT_A_CTX, command(id="bad-1", event_type="not_a_transition")
        )
    assert caught.value.code == "invalid_transition"
    loaded = await harness.repository.get(TENANT_A_CTX, harness.workflow_id)
    assert loaded is not None
    assert loaded.state == "collecting"
    assert loaded.lock_version == 1
    assert (
        await harness.repository.count_transitions(
            TENANT_A_CTX, harness.workflow_id, command_id="bad-1"
        )
        == 0
    )
    assert await harness.repository.count_transitions(
        TENANT_A_CTX, harness.workflow_id
    ) == 1


@pytest.mark.anyio
async def test_tenant_b_cannot_advance_tenant_a_workflow(harness: Harness) -> None:
    with pytest.raises(WorkflowError) as caught:
        await harness.engine.advance(
            TENANT_B_CTX,
            AdvanceCommand(
                workflow_id=harness.workflow_id,
                command_id="cmd-x",
                event_type="submit",
            ),
        )
    assert caught.value.code == "not_found"
    assert str(harness.workflow_id) not in caught.value.safe_message
    assert str(TENANT_A) not in caught.value.safe_message
    assert await harness.repository.get(TENANT_B_CTX, harness.workflow_id) is None
    loaded = await harness.repository.get(TENANT_A_CTX, harness.workflow_id)
    assert loaded is not None
    assert loaded.state == "collecting"


@pytest.mark.anyio
async def test_unknown_workflow_is_not_found(harness: Harness) -> None:
    with pytest.raises(WorkflowError) as caught:
        await harness.engine.advance(
            TENANT_A_CTX,
            AdvanceCommand(
                workflow_id=uuid4(), command_id="cmd-missing", event_type="submit"
            ),
        )
    assert caught.value.code == "not_found"


@pytest.mark.anyio
async def test_happy_path_reaches_completed(harness: Harness) -> None:
    engine = harness.engine
    workflow_id = harness.workflow_id
    submitted = await engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(workflow_id=workflow_id, command_id="cmd-1", event_type="submit"),
    )
    confirmed = await engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=workflow_id, command_id="cmd-2", event_type="confirm"
        ),
    )
    completed = await engine.advance(
        TENANT_A_CTX,
        AdvanceCommand(
            workflow_id=workflow_id, command_id="cmd-3", event_type="succeed"
        ),
    )
    assert submitted.state == "awaiting_confirmation"
    assert confirmed.state == "executing"
    assert completed.state == "completed"
    assert completed.status == "completed"
    loaded = await harness.repository.get(TENANT_A_CTX, workflow_id)
    assert loaded is not None
    assert loaded.state == "completed"
    assert loaded.lock_version == 4
