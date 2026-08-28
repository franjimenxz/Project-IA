from ia_mcp.evals.quality_report import (
    QualityReport,
    ResilienceEvidence,
    aggregate_quality,
)
from ia_mcp.evals.report import EvalReport
from ia_mcp.evals.scorers import TrajectoryScore
from ia_mcp.performance.scenarios import run_scenario


def _eval_report(*, passed: bool = True) -> EvalReport:
    scores = {
        "tenant": 1.0,
        "tools": 1.0,
        "sources": 1.0,
        "policy": 1.0,
        "workflow": 1.0,
        "outcome": 1.0,
        "skill": 1.0,
        "groundedness": 1.0,
    }
    return EvalReport.model_validate(
        {
            "passed": passed,
            "commit": "abc123",
            "dataset_hash": "d" * 64,
            "dataset_path": "evals/datasets/mvp.jsonl",
            "model_provider": "fake",
            "model_name": "fake-llm",
            "config_summary": {"suite": "smoke", "config_version": 1},
            "environment": {"python": "3.13.12", "platform": "test"},
            "category_averages": scores,
                "critical_failures": () if passed else ("uc-08-tenant-a-tool-forbidden:forbidden_tool",),
            "case_results": (
                TrajectoryScore(
                    case_id="uc-08-tenant-a-hours",
                    passed=passed,
                    critical=True,
                    critical_failures=() if passed else ("forbidden_tool:appointments.create",),
                    category_scores=scores,
                ),
            ),
            "flakiness": {},
            "gate_reason": "pass" if passed else "critical_failure",
        }
    )


def _resilience(*, passed: bool = True) -> ResilienceEvidence:
    return ResilienceEvidence(
        passed=passed,
        test_count=32,
            failed=() if passed else ("tests/resilience/test_dependencies.py::test_mcp",),
        commit="abc123",
        source="tests/resilience",
        outcomes=("retry", "recovery", "manual_review"),
    )


def test_quality_gate_requires_eval_resilience_and_performance() -> None:
    report = aggregate_quality(
        eval_report=_eval_report(),
        resilience=_resilience(),
        performance=run_scenario("mvp-baseline"),
    )
    assert isinstance(report, QualityReport)
    assert report.passed is True
    assert report.eval_passed is True
    assert report.resilience_passed is True
    assert report.performance_passed is True
    assert report.production_slo_declared is False
    assert report.commit
    assert report.dataset_hash


def test_quality_gate_fails_when_eval_report_fails() -> None:
    report = aggregate_quality(
        eval_report=_eval_report(passed=False),
        resilience=_resilience(),
        performance=run_scenario("mvp-baseline"),
    )
    assert report.passed is False
    assert report.gate_reason == "eval_failed"


def test_quality_gate_fails_when_resilience_evidence_fails() -> None:
    report = aggregate_quality(
        eval_report=_eval_report(),
        resilience=_resilience(passed=False),
        performance=run_scenario("mvp-baseline"),
    )
    assert report.passed is False
    assert report.gate_reason == "resilience_failed"


def test_quality_gate_fails_when_performance_regresses() -> None:
    current = run_scenario("mvp-baseline")
    baseline = current.model_copy(
        update={
            "latency_by_span": {
                name: item.model_copy(update={"p95_ms": max(item.p95_ms - 1.0, 0.0)})
                for name, item in current.latency_by_span.items()
            }
        }
    )
    report = aggregate_quality(
        eval_report=_eval_report(),
        resilience=_resilience(),
        performance=current,
        performance_baseline=baseline,
    )
    assert report.passed is False
    assert report.gate_reason == "performance_regression"


def test_quality_report_reproduces_commit_dataset_model_and_environment() -> None:
    performance = run_scenario("mvp-baseline")
    report = aggregate_quality(
        eval_report=_eval_report(),
        resilience=_resilience(),
        performance=performance,
    )
    assert report.commit == performance.commit
    assert report.dataset_hash == performance.dataset_hash
    assert report.model_provider == "fake"
    assert report.environment["python"]
    markdown = report.to_markdown()
    assert performance.commit in markdown
    assert "deferred until EXT-007" in markdown
    assert "eval" in markdown
    assert "resilience" in markdown
    assert "performance" in markdown
