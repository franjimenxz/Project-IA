from pydantic import ValidationError

from ia_mcp.performance.models import (
    ErrorMetrics,
    PerformanceReport,
    QueueAgeMetrics,
    ThroughputMetrics,
    build_report,
    compare_reports,
    span_latency,
)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "scenario": "mvp-baseline",
        "passed": True,
        "commit": "abc123",
        "dataset_hash": "d" * 64,
        "dataset_path": "evals/datasets/mvp.jsonl",
        "model_provider": "fake",
        "model_name": "fake-llm",
        "config_summary": {"scenario": "mvp-baseline", "config_version": 1},
        "environment": {"python": "3.13.12", "platform": "test"},
        "throughput": {
            "operations_per_second": 10.0,
            "completed": 20,
            "duration_ms": 2000.0,
        },
        "latency_by_span": {
            "knowledge.search": {
                "span_name": "knowledge.search",
                "p50_ms": 10.0,
                "p95_ms": 20.0,
                "p99_ms": 25.0,
                "max_ms": 30.0,
                "count": 4,
                "budget_ms": 200.0,
            }
        },
        "errors": {"count": 0, "rate": 0.0, "by_code": {}},
        "queue_age": {
            "p50_ms": 100.0,
            "p95_ms": 200.0,
            "max_ms": 250.0,
            "depth": 8,
        },
        "production_slo_declared": False,
        "gate_reason": "pass",
    }
    payload.update(overrides)
    return payload


def test_report_without_latency_errors_or_queue_metrics_is_rejected() -> None:
    payload = _payload()
    del payload["latency_by_span"]
    del payload["errors"]
    del payload["queue_age"]

    try:
        PerformanceReport.model_validate(payload)
    except ValidationError as exc:
        missing = {error["loc"][0] for error in exc.errors() if error["type"] == "missing"}
        assert "latency_by_span" in missing
        assert "errors" in missing
        assert "queue_age" in missing
        return
    raise AssertionError("expected ValidationError for missing load metrics")


def test_report_with_empty_latency_by_span_is_rejected() -> None:
    try:
        PerformanceReport.model_validate(_payload(latency_by_span={}))
    except ValidationError as exc:
        assert any("latency_by_span" in error["loc"] for error in exc.errors())
        return
    raise AssertionError("expected ValidationError for empty latency_by_span")


def test_report_does_not_declare_production_slo() -> None:
    try:
        PerformanceReport.model_validate(_payload(production_slo_declared=True))
    except ValidationError:
        return
    raise AssertionError("expected ValidationError when production SLO is declared")


def _report(*, search_p95: float = 20.0, errors: float = 0.0) -> PerformanceReport:
    return PerformanceReport.model_validate(
        _payload(
            latency_by_span={
                "knowledge.search": {
                    "span_name": "knowledge.search",
                    "p50_ms": 10.0,
                    "p95_ms": search_p95,
                    "p99_ms": search_p95,
                    "max_ms": search_p95,
                    "count": 4,
                    "budget_ms": 200.0,
                }
            },
            errors={"count": int(errors > 0), "rate": errors, "by_code": {}},
        )
    )


def test_compare_reports_regression_when_span_latency_worsens() -> None:
    comparison = compare_reports(baseline=_report(search_p95=20.0), current=_report(search_p95=80.0))
    assert comparison.passed is False
    assert comparison.gate_reason == "metric_regression"
    assert any(item.metric == "latency.knowledge.search.p95_ms" for item in comparison.regressions)


def test_compare_reports_passes_when_metrics_match_baseline() -> None:
    report = _report()
    comparison = compare_reports(baseline=report, current=report)
    assert comparison.passed is True
    assert comparison.gate_reason == "pass"


def test_span_latency_records_percentiles_and_budget() -> None:
    latency = span_latency("knowledge.search", (10.0, 12.0, 40.0, 18.0), budget_ms=200.0)
    assert latency.count == 4
    assert latency.p50_ms == 15.0
    assert latency.max_ms == 40.0
    assert latency.budget_ms == 200.0
    _ = ThroughputMetrics(operations_per_second=1.0, completed=1, duration_ms=1000.0)
    _ = ErrorMetrics(count=0, rate=0.0)
    _ = QueueAgeMetrics(p50_ms=1.0, p95_ms=2.0, max_ms=3.0, depth=1)


def test_build_report_fails_when_span_p95_exceeds_budget() -> None:
    search = span_latency("knowledge.search", (10.0, 250.0), budget_ms=200.0)
    report = build_report(
        scenario="mvp-baseline",
        latency_by_span={"knowledge.search": search},
        throughput=ThroughputMetrics(operations_per_second=10.0, completed=2, duration_ms=200.0),
        errors=ErrorMetrics(count=0, rate=0.0),
        queue_age_metrics=QueueAgeMetrics(p50_ms=1.0, p95_ms=2.0, max_ms=3.0, depth=1),
        dataset_hash="d" * 64,
        dataset_path="evals/datasets/mvp.jsonl",
        model_provider="fake",
        model_name="fake-llm",
        config_summary={"scenario": "mvp-baseline"},
        commit="abc123",
        environment={"python": "3.13.12", "platform": "test"},
    )
    assert search.p95_ms > search.budget_ms
    assert report.passed is False
    assert "knowledge.search:p95>" in report.gate_reason


def test_compare_reports_fails_when_current_omits_baseline_span() -> None:
    baseline = _report(search_p95=20.0)
    current = PerformanceReport.model_validate(
        _payload(
            latency_by_span={
                "llm.generate": {
                    "span_name": "llm.generate",
                    "p50_ms": 10.0,
                    "p95_ms": 20.0,
                    "p99_ms": 20.0,
                    "max_ms": 20.0,
                    "count": 2,
                    "budget_ms": 500.0,
                }
            }
        )
    )
    comparison = compare_reports(baseline=baseline, current=current)
    assert comparison.passed is False
    assert any(item.metric == "latency.knowledge.search.missing" for item in comparison.regressions)
