from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ia_mcp.evals.report import capture_commit, capture_environment
from ia_mcp.observability.redaction import redact

SPAN_BUDGETS_MS: dict[str, float] = {
    "channel.receive": 50.0,
    "tenant.resolve": 50.0,
    "conversation.load": 50.0,
    "agent.run": 800.0,
    "context.compile": 80.0,
    "knowledge.search": 200.0,
    "llm.generate": 500.0,
    "skill.route": 40.0,
    "workflow.advance": 100.0,
    "tool.execute": 200.0,
    "scheduler.dispatch": 100.0,
    "channel.send": 50.0,
}

THROUGHPUT_MIN_OPS = 1.0
ERROR_RATE_MAX = 0.0
QUEUE_AGE_P95_MAX_MS = 5_000.0


def _ms(value: float) -> float:
    return round(value, 3)


class SpanLatency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    span_name: str
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    count: int
    budget_ms: float


class ThroughputMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operations_per_second: float
    completed: int
    duration_ms: float


class ErrorMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int
    rate: float
    by_code: dict[str, int] = Field(default_factory=dict)


class QueueAgeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    p50_ms: float
    p95_ms: float
    max_ms: float
    depth: int


class MetricRegression(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str
    baseline: float
    current: float


class PerformanceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario: str
    passed: bool
    commit: str
    dataset_hash: str
    dataset_path: str
    model_provider: str
    model_name: str
    config_summary: dict[str, object]
    environment: dict[str, str]
    latency_by_span: dict[str, SpanLatency]
    throughput: ThroughputMetrics
    errors: ErrorMetrics
    queue_age: QueueAgeMetrics
    production_slo_declared: Literal[False] = False
    gate_reason: str = "pass"
    baseline_hash: str | None = None

    @field_validator("latency_by_span")
    @classmethod
    def latency_by_span_is_present(
        cls, value: dict[str, SpanLatency]
    ) -> dict[str, SpanLatency]:
        if not value:
            raise ValueError("latency_by_span must include at least one span")
        return value

    @field_validator("production_slo_declared")
    @classmethod
    def production_slo_is_deferred(cls, value: bool) -> bool:
        if value:
            raise ValueError("production SLO requires EXT-007")
        return value

    @model_validator(mode="after")
    def required_load_metrics_are_present(self) -> PerformanceReport:
        if self.errors is None or self.queue_age is None or self.throughput is None:
            raise ValueError("throughput, errors and queue_age are required")
        return self


class PerformanceComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    regressions: tuple[MetricRegression, ...]
    budget_failures: tuple[str, ...]
    provenance_failures: tuple[str, ...]
    gate_reason: str


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (q / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def span_latency(
    span_name: str,
    samples_ms: Sequence[float],
    *,
    budget_ms: float | None = None,
) -> SpanLatency:
    samples = tuple(samples_ms)
    budget = budget_ms if budget_ms is not None else SPAN_BUDGETS_MS.get(span_name, 1_000.0)
    return SpanLatency(
        span_name=span_name,
        p50_ms=_ms(percentile(samples, 50.0)),
        p95_ms=_ms(percentile(samples, 95.0)),
        p99_ms=_ms(percentile(samples, 99.0)),
        max_ms=_ms(max(samples) if samples else 0.0),
        count=len(samples),
        budget_ms=_ms(budget),
    )


def queue_age(samples_ms: Sequence[float]) -> QueueAgeMetrics:
    samples = tuple(samples_ms)
    return QueueAgeMetrics(
        p50_ms=_ms(percentile(samples, 50.0)),
        p95_ms=_ms(percentile(samples, 95.0)),
        max_ms=_ms(max(samples) if samples else 0.0),
        depth=len(samples),
    )


def summarize_latency(samples_by_span: Mapping[str, Sequence[float]]) -> dict[str, SpanLatency]:
    return {
        name: span_latency(name, samples)
        for name, samples in samples_by_span.items()
        if samples
    }


def report_hash(report: PerformanceReport) -> str:
    payload = report.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def file_bytes_hash(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def build_report(
    *,
    scenario: str,
    latency_by_span: Mapping[str, SpanLatency],
    throughput: ThroughputMetrics,
    errors: ErrorMetrics,
    queue_age_metrics: QueueAgeMetrics,
    dataset_hash: str,
    dataset_path: str,
    model_provider: str,
    model_name: str,
    config_summary: Mapping[str, object],
    commit: str | None = None,
    environment: Mapping[str, str] | None = None,
    baseline_hash: str | None = None,
) -> PerformanceReport:
    budget_failures = tuple(
        f"{name}:p95>{item.budget_ms}"
        for name, item in latency_by_span.items()
        if item.p95_ms > item.budget_ms
    )
    extra_failures: list[str] = []
    if throughput.operations_per_second < THROUGHPUT_MIN_OPS:
        extra_failures.append("throughput_below_design_budget")
    if errors.rate > ERROR_RATE_MAX:
        extra_failures.append("error_rate_above_design_budget")
    if queue_age_metrics.p95_ms > QUEUE_AGE_P95_MAX_MS:
        extra_failures.append("queue_age_above_design_budget")
    failures = (*budget_failures, *extra_failures)
    passed = not failures
    reason = "pass" if passed else failures[0]
    return PerformanceReport(
        scenario=scenario,
        passed=passed,
        commit=commit if commit is not None else capture_commit(),
        dataset_hash=dataset_hash,
        dataset_path=dataset_path,
        model_provider=model_provider,
        model_name=model_name,
        config_summary=dict(config_summary),
        environment=dict(environment) if environment is not None else capture_environment(),
        latency_by_span=dict(latency_by_span),
        throughput=ThroughputMetrics(
            operations_per_second=_ms(throughput.operations_per_second),
            completed=throughput.completed,
            duration_ms=_ms(throughput.duration_ms),
        ),
        errors=errors,
        queue_age=queue_age_metrics,
        production_slo_declared=False,
        gate_reason=reason,
        baseline_hash=baseline_hash,
    )


def compare_reports(
    *, baseline: PerformanceReport, current: PerformanceReport
) -> PerformanceComparison:
    regressions: list[MetricRegression] = []
    provenance: list[str] = []
    if baseline.dataset_hash != current.dataset_hash:
        provenance.append("dataset_hash")
    if (baseline.model_provider, baseline.model_name) != (
        current.model_provider,
        current.model_name,
    ):
        provenance.append("model")
    if baseline.scenario != current.scenario:
        provenance.append("scenario")
    spans = dict.fromkeys([*baseline.latency_by_span, *current.latency_by_span])
    for name in spans:
        base_span = baseline.latency_by_span.get(name)
        current_span = current.latency_by_span.get(name)
        if base_span is None or current_span is None:
            regressions.append(
                MetricRegression(
                    metric=f"latency.{name}.missing",
                    baseline=0.0 if base_span is None else base_span.p95_ms,
                    current=0.0 if current_span is None else current_span.p95_ms,
                )
            )
            continue
        if current_span.p95_ms > base_span.p95_ms:
            regressions.append(
                MetricRegression(
                    metric=f"latency.{name}.p95_ms",
                    baseline=base_span.p95_ms,
                    current=current_span.p95_ms,
                )
            )
    if current.throughput.operations_per_second < baseline.throughput.operations_per_second:
        regressions.append(
            MetricRegression(
                metric="throughput.operations_per_second",
                baseline=baseline.throughput.operations_per_second,
                current=current.throughput.operations_per_second,
            )
        )
    if current.errors.rate > baseline.errors.rate:
        regressions.append(
            MetricRegression(
                metric="errors.rate",
                baseline=baseline.errors.rate,
                current=current.errors.rate,
            )
        )
    if current.queue_age.p95_ms > baseline.queue_age.p95_ms:
        regressions.append(
            MetricRegression(
                metric="queue_age.p95_ms",
                baseline=baseline.queue_age.p95_ms,
                current=current.queue_age.p95_ms,
            )
        )
    budget_failures = tuple(
        f"{name}:p95>{item.budget_ms}"
        for name, item in current.latency_by_span.items()
        if item.p95_ms > item.budget_ms
    )
    if provenance:
        reason = f"{provenance[0]}_mismatch"
        passed = False
    elif regressions:
        reason = "metric_regression"
        passed = False
    elif budget_failures:
        reason = "budget_exceeded"
        passed = False
    elif not current.passed:
        reason = current.gate_reason
        passed = False
    else:
        reason = "pass"
        passed = True
    return PerformanceComparison(
        passed=passed,
        regressions=tuple(regressions),
        budget_failures=budget_failures,
        provenance_failures=tuple(provenance),
        gate_reason=reason,
    )


def report_to_json(report: PerformanceReport) -> str:
    payload = report.model_dump(mode="json")
    return redact(json.dumps(payload, indent=2, sort_keys=True))


def report_to_markdown(report: PerformanceReport) -> str:
    lines = [
        "# Performance report",
        "",
        f"- gate: {'PASS' if report.passed else 'FAIL'} ({report.gate_reason})",
        f"- scenario: `{report.scenario}`",
        f"- commit: `{report.commit}`",
        f"- dataset: `{report.dataset_path}` hash `{report.dataset_hash}`",
        f"- model: {report.model_provider}/{report.model_name}",
        f"- config: `{json.dumps(report.config_summary, sort_keys=True)}`",
        (
            f"- environment: python {report.environment.get('python', 'unknown')}"
            f" / {report.environment.get('platform', 'unknown')}"
        ),
        "- production_slo: deferred until EXT-007",
        "",
        "## Latency by span (design budgets, not production SLO)",
        "",
    ]
    for name, item in sorted(report.latency_by_span.items()):
        lines.append(
            f"- {name}: p50={item.p50_ms:.1f}ms p95={item.p95_ms:.1f}ms "
            f"p99={item.p99_ms:.1f}ms max={item.max_ms:.1f}ms "
            f"n={item.count} budget={item.budget_ms:.1f}ms"
        )
    lines.extend(
        [
            "",
            "## Throughput / errors / queue age",
            "",
            (
                f"- throughput: {report.throughput.operations_per_second:.2f} ops/s "
                f"({report.throughput.completed} ops in {report.throughput.duration_ms:.1f}ms)"
            ),
            f"- errors: count={report.errors.count} rate={report.errors.rate:.3f}",
            (
                f"- queue age: p50={report.queue_age.p50_ms:.1f}ms "
                f"p95={report.queue_age.p95_ms:.1f}ms max={report.queue_age.max_ms:.1f}ms "
                f"depth={report.queue_age.depth}"
            ),
            "",
        ]
    )
    return redact("\n".join(lines))
