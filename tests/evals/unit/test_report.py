from ia_mcp.evals.report import EvalReport, build_report, compare_reports
from ia_mcp.evals.scorers import TrajectoryScore


def _report(*, tools: float, tenant: float = 1.0) -> EvalReport:
    return EvalReport.model_validate(
        {
            "passed": tools >= 1.0 and tenant >= 1.0,
            "commit": "abc123",
            "dataset_hash": "d" * 64,
            "dataset_path": "evals/datasets/mvp.jsonl",
            "model_provider": "fake",
            "model_name": "fake-llm",
            "config_summary": {"suite": "smoke", "config_version": 1},
            "environment": {"python": "3.13.12", "platform": "test"},
            "category_averages": {
                "tenant": tenant,
                "tools": tools,
                "sources": 1.0,
                "skill": 1.0,
                "groundedness": 1.0,
                "policy": 1.0,
                "workflow": 1.0,
                "outcome": 1.0,
            },
            "critical_failures": (),
            "case_results": (),
            "flakiness": {},
        }
    )


def test_baseline_regression_is_reported_by_category() -> None:
    comparison = compare_reports(
        baseline=_report(tools=1.0),
        current=_report(tools=0.5),
    )
    assert comparison.passed is False
    assert "tools" in comparison.regressions
    assert comparison.regressions["tools"].baseline == 1.0
    assert comparison.regressions["tools"].current == 0.5


def test_matching_baseline_does_not_regress() -> None:
    comparison = compare_reports(
        baseline=_report(tools=1.0),
        current=_report(tools=1.0),
    )
    assert comparison.passed is True
    assert comparison.regressions == {}


def test_critical_failure_fails_gate_despite_high_averages() -> None:
    passing = TrajectoryScore(
        case_id="uc-08-tenant-a-hours",
        passed=True,
        critical=True,
        critical_failures=(),
        category_scores={
            "tenant": 1.0,
            "skill": 1.0,
            "sources": 1.0,
            "tools": 1.0,
            "workflow": 1.0,
            "outcome": 1.0,
            "groundedness": 1.0,
            "policy": 1.0,
        },
    )
    failing = TrajectoryScore(
        case_id="uc-08-tenant-a-tool-forbidden",
        passed=False,
        critical=True,
        critical_failures=("forbidden_tool:appointments.create",),
        category_scores={
            "tenant": 1.0,
            "skill": 1.0,
            "sources": 1.0,
            "tools": 0.0,
            "workflow": 1.0,
            "outcome": 1.0,
            "groundedness": 1.0,
            "policy": 0.0,
        },
    )
    report = build_report(
        (passing, passing, passing, passing, failing),
        dataset_path="evals/datasets/mvp.jsonl",
        dataset_hash="b" * 64,
        model_provider="fake",
        model_name="fake-llm",
        config_summary={"suite": "smoke"},
        commit="abc123",
        environment={"python": "3.13.12", "platform": "test"},
    )
    assert report.category_averages["skill"] == 1.0
    assert report.category_averages["groundedness"] == 1.0
    assert report.passed is False
    assert report.gate_reason == "critical_failure"
    assert "uc-08-tenant-a-tool-forbidden:forbidden_tool:appointments.create" in (
        report.critical_failures
    )
