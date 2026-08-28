from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, Literal, Protocol
from uuid import UUID, uuid4

from ia_mcp.evals.runner import EvalRunner, load_eval_cases, tenant_context_for
from ia_mcp.evals.validator import validate_dataset
from ia_mcp.knowledge.models import KnowledgeHit, KnowledgeQuery
from ia_mcp.performance.models import (
    ErrorMetrics,
    PerformanceReport,
    ThroughputMetrics,
    build_report,
    queue_age,
    summarize_latency,
)
from ia_mcp.scheduling.models import (
    AppointmentScheduledEvent,
    ScheduledJob,
    SchedulingOutbox,
    SchedulingPolicy,
)
from ia_mcp.scheduling.service import ReminderScheduler
from ia_mcp.tenancy.models import TenantContext
from ia_mcp.workflows.engine import WorkflowEngine
from ia_mcp.workflows.models import (
    AdvanceCommand,
    OutboxEvent,
    StartWorkflow,
    WorkflowExecution,
    WorkflowState,
    WorkflowTransition,
)
from ia_mcp.workflows.ports import WorkflowError

SCENARIO_NAMES: tuple[str, ...] = ("mvp-baseline",)
DEFAULT_DATASET = Path("evals/datasets/mvp.jsonl")
_DOC = UUID("aaaaaaaa-0000-4000-8000-000000000001")
_CLOCK = datetime(2026, 8, 28, 16, 0, tzinfo=UTC)
_CORPUS_SIZES: tuple[int, ...] = (10, 50, 100)
_QUEUE_AGES_MS: tuple[int, ...] = (100, 200, 350, 500, 800, 1200, 1800, 2400)
_SLOW_UPSTREAM_MS = 120.0

_SPAN_COST_MS: dict[str, float] = {
    "tenant.resolve": 5.0,
    "conversation.load": 8.0,
    "agent.run": 40.0,
    "context.compile": 6.0,
    "knowledge.search": 12.0,
    "llm.generate": 30.0,
    "skill.route": 3.0,
    "workflow.advance": 15.0,
    "tool.execute": 10.0,
    "scheduler.dispatch": 10.0,
}


class _Recorder(Protocol):
    def __call__(self, span: str, *, corpus: int = 0, slow: bool = False) -> None: ...


class _Fail(Protocol):
    def __call__(self, code: str) -> None: ...


def run_scenario(name: str) -> PerformanceReport:
    if name == "mvp-baseline":
        return asyncio.run(_run_mvp_baseline())
    raise ValueError(f"unknown scenario: {name}")


def _span_cost(span: str, *, corpus: int = 0, slow: bool = False) -> float:
    if span not in _SPAN_COST_MS:
        raise ValueError(f"unknown span: {span}")
    if span == "knowledge.search":
        return _SPAN_COST_MS[span] + corpus * 0.2
    if span == "llm.generate" and slow:
        return _SLOW_UPSTREAM_MS
    return _SPAN_COST_MS[span]


async def _run_mvp_baseline() -> PerformanceReport:
    dataset = DEFAULT_DATASET
    validation = validate_dataset(dataset)
    samples: dict[str, list[float]] = defaultdict(list)
    error_codes: dict[str, int] = {}
    completed = 0

    def record(span: str, *, corpus: int = 0, slow: bool = False) -> None:
        samples[span].append(_span_cost(span, corpus=corpus, slow=slow))

    def fail(code: str) -> None:
        error_codes[code] = error_codes.get(code, 0) + 1

    completed += await _concurrent_faq(record, fail)
    completed += await _long_workflows(record, fail)
    completed += await _growing_corpus(record, fail)
    queue_samples, queued = await _queue_burst(record, fail)
    completed += queued
    completed += await _slow_upstream(record, fail)

    duration_ms = sum(value for values in samples.values() for value in values)
    error_count = sum(error_codes.values())
    ops_per_second = 0.0 if duration_ms <= 0 else completed / (duration_ms / 1000.0)
    return build_report(
        scenario="mvp-baseline",
        latency_by_span=summarize_latency(samples),
        throughput=ThroughputMetrics(
            operations_per_second=ops_per_second,
            completed=completed,
            duration_ms=duration_ms,
        ),
        errors=ErrorMetrics(count=error_count, rate=error_count / max(completed, 1), by_code=error_codes),
        queue_age_metrics=queue_age(queue_samples),
        dataset_hash=validation.dataset_hash,
        dataset_path=str(dataset),
        model_provider="fake",
        model_name="fake-llm",
        config_summary={
            "scenario": "mvp-baseline",
            "config_version": 1,
            "production_slo": "deferred_ext_007",
            "tenants": ["tenant_a", "tenant_b"],
        },
    )


async def _concurrent_faq(record: _Recorder, fail: _Fail) -> int:
    cases = [case for case in load_eval_cases(DEFAULT_DATASET) if case.expected_skill == "faq"]
    case_a = next(case for case in cases if case.tenant_fixture == "tenant_a")
    case_b = next(case for case in cases if case.tenant_fixture == "tenant_b")
    runner_a = EvalRunner.for_fake_provider()
    runner_b = EvalRunner.for_fake_provider()
    observed_a, observed_b = await asyncio.gather(
        runner_a.run_case(case_a),
        runner_b.run_case(case_b),
    )
    if observed_a.tenant_id == observed_b.tenant_id:
        fail("tenant_isolation")
        return 0
    for _ in (observed_a, observed_b):
        record("tenant.resolve")
        record("conversation.load")
        record("context.compile")
        record("knowledge.search")
        record("llm.generate")
        record("skill.route")
        record("agent.run")
    return 2


async def _long_workflows(record: _Recorder, fail: _Fail) -> int:
    completed = 0
    for fixture in ("tenant_a", "tenant_b"):
        tenant = tenant_context_for(fixture, 1)
        engine = WorkflowEngine(_InMemoryWorkflowRepository(), _LongWorkflowDefinition())
        started = await engine.start(
            tenant,
            StartWorkflow(
                command_id=f"{fixture}-start",
                workflow_type="performance_long",
                conversation_id=uuid4(),
            ),
        )
        record("workflow.advance")
        completed += 1
        for event, command_id in (
            ("confirm_intent", f"{fixture}-confirm"),
            ("execute", f"{fixture}-execute"),
            ("complete", f"{fixture}-complete"),
        ):
            try:
                await engine.advance(
                    tenant,
                    AdvanceCommand(
                        workflow_id=started.workflow_id,
                        command_id=command_id,
                        event_type=event,
                    ),
                )
            except WorkflowError as exc:
                fail(exc.code)
                continue
            record("workflow.advance")
            completed += 1
    return completed


async def _growing_corpus(record: _Recorder, fail: _Fail) -> int:
    runner = EvalRunner.for_fake_provider()
    if runner.knowledge is None:
        fail("knowledge_missing")
        return 0
    tenant = tenant_context_for("tenant_a", 1)
    completed = 0
    for size in _CORPUS_SIZES:
        runner.knowledge.hits = tuple(_hit(tenant.tenant_id, index) for index in range(size))
        try:
            hits = await runner.knowledge.search(tenant, KnowledgeQuery(text="horario", limit=5))
        except Exception as exc:  # noqa: BLE001 - scenario records typed error codes
            fail(type(exc).__name__)
            continue
        if any(hit.tenant_id != tenant.tenant_id for hit in hits):
            fail("tenant_isolation")
            continue
        record("knowledge.search", corpus=size)
        completed += 1
    return completed


async def _queue_burst(record: _Recorder, fail: _Fail) -> tuple[tuple[float, ...], int]:
    store = _InMemoryJobStore()
    clock = _FixedClock(_CLOCK)
    scheduler = ReminderScheduler(store, clock, SchedulingPolicy())
    ages: list[float] = []
    for index, age_ms in enumerate(_QUEUE_AGES_MS):
        fixture: Literal["tenant_a", "tenant_b"] = "tenant_a" if index % 2 == 0 else "tenant_b"
        tenant = tenant_context_for(fixture, 1)
        starts_at = clock.now() + timedelta(hours=48) - timedelta(milliseconds=age_ms)
        try:
            job = await scheduler.upsert(
                tenant,
                AppointmentScheduledEvent(
                    appointment_id=f"appt-{index}",
                    starts_at=starts_at,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - scenario records typed error codes
            fail(type(exc).__name__)
            continue
        age = (clock.now() - job.scheduled_for).total_seconds() * 1000.0
        ages.append(age)
        record("scheduler.dispatch")
    return tuple(ages), len(ages)


async def _slow_upstream(record: _Recorder, fail: _Fail) -> int:
    runner = EvalRunner.for_fake_provider()
    if runner.llm is None:
        fail("llm_missing")
        return 0
    cases = [case for case in load_eval_cases(DEFAULT_DATASET) if case.expected_skill == "faq"]
    case = next(case for case in cases if case.tenant_fixture == "tenant_a")
    try:
        await runner.run_case(case)
    except Exception as exc:  # noqa: BLE001 - scenario records typed error codes
        fail(type(exc).__name__)
        return 0
    record("llm.generate", slow=True)
    record("agent.run")
    return 1


def _hit(tenant_id: UUID, index: int) -> KnowledgeHit:
    return KnowledgeHit(
        tenant_id=tenant_id,
        source_id=f"kb-synth-{index}",
        text="Synthetic catalog snippet.",
        score=0.9,
        document_id=_DOC,
        document_version=1,
        page=1,
    )


class _FixedClock:
    def __init__(self, instant: datetime) -> None:
        self._now = instant

    def now(self) -> datetime:
        return self._now


class _InMemoryJobStore:
    def __init__(self) -> None:
        self._jobs: dict[tuple[UUID, str, str], ScheduledJob] = {}

    async def get(self, tenant: TenantContext, job_id: UUID) -> ScheduledJob | None:
        del tenant, job_id
        return None

    async def get_by_identity(
        self, tenant: TenantContext, job_type: str, business_key: str
    ) -> ScheduledJob | None:
        return self._jobs.get((tenant.tenant_id, job_type, business_key))

    async def put(self, job: ScheduledJob) -> ScheduledJob:
        self._jobs[(job.tenant_id, job.type, job.business_key)] = job
        return job

    async def save(self, job: ScheduledJob) -> ScheduledJob:
        return await self.put(job)

    async def claim_due(
        self, *, now: datetime, owner: str, lock_until: datetime
    ) -> ScheduledJob | None:
        del now, owner, lock_until
        return None

    async def put_outbox(self, event: SchedulingOutbox) -> bool:
        del event
        return True

    async def has_outbox(
        self, tenant: TenantContext, job_id: UUID, schedule_version: int
    ) -> bool:
        del tenant, job_id, schedule_version
        return False


class _LongWorkflowDefinition:
    _TRANSITIONS: ClassVar[dict[tuple[str, str], WorkflowState]] = {
        ("collecting", "confirm_intent"): "awaiting_confirmation",
        ("awaiting_confirmation", "execute"): "executing",
        ("executing", "complete"): "completed",
    }

    def transition(self, from_state: str, event: str) -> WorkflowState:
        try:
            return self._TRANSITIONS[(from_state, event)]
        except KeyError as exc:
            raise WorkflowError("invalid_transition", "Resource not found") from exc


class _InMemoryWorkflowRepository:
    def __init__(self) -> None:
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
        if execution.tenant_id != tenant.tenant_id:
            raise WorkflowError("not_found", "Resource not found")
        key = (tenant.tenant_id, execution.id)
        if key in self._executions:
            raise WorkflowError("conflict", "Workflow was updated concurrently.")
        self._executions[key] = execution
        self._transitions.append(transition)
        self._outbox.append(outbox)

    async def get(self, tenant: TenantContext, workflow_id: UUID) -> WorkflowExecution | None:
        return self._executions.get((tenant.tenant_id, workflow_id))

    async def get_by_idempotency(
        self, tenant: TenantContext, idempotency_key_hash: str
    ) -> WorkflowExecution | None:
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
        matches = [
            transition
            for transition in self._transitions
            if transition.tenant_id == tenant.tenant_id and transition.workflow_id == workflow_id
        ]
        return tuple(sorted(matches, key=lambda item: item.sequence))

    async def count_transitions(
        self,
        tenant: TenantContext,
        workflow_id: UUID,
        *,
        command_id: str | None = None,
    ) -> int:
        total = 0
        for transition in self._transitions:
            if transition.tenant_id != tenant.tenant_id or transition.workflow_id != workflow_id:
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
        if execution.tenant_id != tenant.tenant_id:
            raise WorkflowError("not_found", "Resource not found")
        key = (tenant.tenant_id, execution.id)
        current = self._executions.get(key)
        if current is None:
            raise WorkflowError("not_found", "Resource not found")
        if current.lock_version != expected_lock_version:
            raise WorkflowError("conflict", "Workflow was updated concurrently.")
        self._executions[key] = execution
        self._transitions.append(transition)
        self._outbox.append(outbox)
        return execution
