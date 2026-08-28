from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from ia_mcp.evals.quality_report import (
    QualityReport,
    ResilienceEvidence,
    aggregate_quality,
    main,
)
from ia_mcp.evals.report import EvalReport, report_to_json
from ia_mcp.evals.scorers import TrajectoryScore
from ia_mcp.performance.models import report_to_json as performance_to_json
from ia_mcp.performance.scenarios import run_scenario

_JUNIT_TWO_PASSED = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="2" failures="0" errors="0" skipped="0">
    <testcase classname="tests.resilience.test_dependencies" name="test_a"/>
    <testcase classname="tests.resilience.test_dependencies" name="test_b"/>
  </testsuite>
</testsuites>
"""


def _eval_report(*, passed: bool = True, commit: str = "abc123") -> EvalReport:
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
            "commit": commit,
            "dataset_hash": "d" * 64,
            "dataset_path": "evals/datasets/mvp.jsonl",
            "model_provider": "fake",
            "model_name": "fake-llm",
            "config_summary": {"suite": "smoke", "config_version": 1},
            "environment": {"python": "3.13.12", "platform": "test"},
            "category_averages": scores,
            "critical_failures": ()
            if passed
            else ("uc-08-tenant-a-tool-forbidden:forbidden_tool",),
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


def _resilience(*, passed: bool = True, commit: str = "abc123", test_count: int = 32) -> ResilienceEvidence:
    return ResilienceEvidence(
        passed=passed,
        test_count=test_count,
        failed=() if passed else ("tests/resilience/test_dependencies.py::test_mcp",),
        commit=commit,
        source="tests/resilience",
        outcomes=("retry", "recovery", "manual_review"),
    )


def _write_gate_inputs(
    tmp_path: Path,
    *,
    eval_commit: str,
    resilience_commit: str,
    performance_commit: str | None = None,
) -> tuple[Path, Path, Path]:
    performance = run_scenario("mvp-baseline")
    if performance_commit is not None:
        performance = performance.model_copy(update={"commit": performance_commit})
    eval_path = tmp_path / "evals.json"
    resilience_path = tmp_path / "resilience.json"
    performance_path = tmp_path / "performance.json"
    eval_path.write_text(
        report_to_json(_eval_report(commit=eval_commit)),
        encoding="utf-8",
    )
    resilience_path.write_text(
        _resilience(commit=resilience_commit).model_dump_json(indent=2),
        encoding="utf-8",
    )
    performance_path.write_text(performance_to_json(performance), encoding="utf-8")
    return eval_path, resilience_path, performance_path


def test_quality_gate_requires_eval_resilience_and_performance() -> None:
    performance = run_scenario("mvp-baseline")
    report = aggregate_quality(
        eval_report=_eval_report(commit=performance.commit),
        resilience=_resilience(commit=performance.commit),
        performance=performance,
    )
    assert isinstance(report, QualityReport)
    assert report.passed is True
    assert report.eval_passed is True
    assert report.resilience_passed is True
    assert report.performance_passed is True
    assert report.production_slo_declared is False
    assert report.commit
    assert report.dataset_hash
    assert report.performance_baseline_hash is None


def test_quality_gate_fails_when_eval_report_fails() -> None:
    performance = run_scenario("mvp-baseline")
    report = aggregate_quality(
        eval_report=_eval_report(passed=False, commit=performance.commit),
        resilience=_resilience(commit=performance.commit),
        performance=performance,
    )
    assert report.passed is False
    assert report.gate_reason == "eval_failed"


def test_quality_gate_fails_when_resilience_evidence_fails() -> None:
    performance = run_scenario("mvp-baseline")
    report = aggregate_quality(
        eval_report=_eval_report(commit=performance.commit),
        resilience=_resilience(passed=False, commit=performance.commit),
        performance=performance,
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
        eval_report=_eval_report(commit=current.commit),
        resilience=_resilience(commit=current.commit),
        performance=current,
        performance_baseline=baseline,
        performance_baseline_hash="b" * 64,
    )
    assert report.passed is False
    assert report.gate_reason == "performance_regression"
    assert report.performance_baseline_hash == "b" * 64


def test_quality_report_reproduces_commit_dataset_model_and_environment() -> None:
    performance = run_scenario("mvp-baseline")
    report = aggregate_quality(
        eval_report=_eval_report(commit=performance.commit),
        resilience=_resilience(commit=performance.commit),
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


def test_quality_gate_fails_when_eval_commit_disagrees() -> None:
    performance = run_scenario("mvp-baseline")
    report = aggregate_quality(
        eval_report=_eval_report(commit="deadbeef"),
        resilience=_resilience(commit=performance.commit),
        performance=performance,
    )
    assert report.passed is False
    assert report.gate_reason == "provenance_mismatch"


def test_resilience_evidence_rejects_passed_with_zero_tests() -> None:
    try:
        ResilienceEvidence(
            passed=True,
            test_count=0,
            commit="abc123",
            source="tests/resilience",
        )
    except ValidationError:
        return
    raise AssertionError("passed resilience evidence with zero tests must be rejected")


def test_record_resilience_passed_with_zero_tests_exits_nonzero(tmp_path: Path) -> None:
    output = tmp_path / "resilience.json"
    code = main(
        [
            "record-resilience",
            "--passed",
            "--source",
            "tests/resilience",
            "--output",
            str(output),
        ]
    )
    assert code != 0
    if output.is_file():
        evidence = ResilienceEvidence.model_validate_json(output.read_text(encoding="utf-8"))
        assert evidence.passed is False


def test_record_resilience_from_junit_xml(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    output = tmp_path / "resilience.json"
    junit.write_text(_JUNIT_TWO_PASSED, encoding="utf-8")
    code = main(
        [
            "record-resilience",
            "--junit",
            str(junit),
            "--source",
            "tests/resilience",
            "--output",
            str(output),
        ]
    )
    assert code == 0
    evidence = ResilienceEvidence.model_validate_json(output.read_text(encoding="utf-8"))
    assert evidence.passed is True
    assert evidence.test_count == 2
    assert evidence.commit


def test_gate_missing_baseline_exits_nonzero(tmp_path: Path) -> None:
    performance = run_scenario("mvp-baseline")
    eval_path, resilience_path, performance_path = _write_gate_inputs(
        tmp_path,
        eval_commit=performance.commit,
        resilience_commit=performance.commit,
        performance_commit=performance.commit,
    )
    output = tmp_path / "quality.json"
    code = main(
        [
            "gate",
            "--eval",
            str(eval_path),
            "--resilience",
            str(resilience_path),
            "--performance",
            str(performance_path),
            "--baseline",
            str(tmp_path / "absent.json"),
            "--output",
            str(output),
        ]
    )
    assert code != 0


def test_gate_cli_exits_nonzero_when_eval_fails(tmp_path: Path) -> None:
    performance = run_scenario("mvp-baseline")
    eval_path = tmp_path / "evals.json"
    resilience_path = tmp_path / "resilience.json"
    performance_path = tmp_path / "performance.json"
    eval_path.write_text(
        report_to_json(_eval_report(passed=False, commit=performance.commit)),
        encoding="utf-8",
    )
    resilience_path.write_text(
        _resilience(commit=performance.commit).model_dump_json(indent=2),
        encoding="utf-8",
    )
    performance_path.write_text(performance_to_json(performance), encoding="utf-8")
    output = tmp_path / "quality.json"
    code = main(
        [
            "gate",
            "--eval",
            str(eval_path),
            "--resilience",
            str(resilience_path),
            "--performance",
            str(performance_path),
            "--output",
            str(output),
        ]
    )
    assert code != 0
    report = QualityReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert report.passed is False
    assert report.gate_reason == "eval_failed"


def test_compared_and_skipped_baseline_artifacts_differ(tmp_path: Path) -> None:
    performance = run_scenario("mvp-baseline")
    eval_path, resilience_path, performance_path = _write_gate_inputs(
        tmp_path,
        eval_commit=performance.commit,
        resilience_commit=performance.commit,
        performance_commit=performance.commit,
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(performance_path.read_text(encoding="utf-8"), encoding="utf-8")
    expected_hash = sha256(baseline.read_bytes()).hexdigest()
    skipped_out = tmp_path / "skipped.json"
    compared_out = tmp_path / "compared.json"
    skipped_code = main(
        [
            "gate",
            "--eval",
            str(eval_path),
            "--resilience",
            str(resilience_path),
            "--performance",
            str(performance_path),
            "--output",
            str(skipped_out),
        ]
    )
    compared_code = main(
        [
            "gate",
            "--eval",
            str(eval_path),
            "--resilience",
            str(resilience_path),
            "--performance",
            str(performance_path),
            "--baseline",
            str(baseline),
            "--output",
            str(compared_out),
        ]
    )
    assert skipped_code == 0
    assert compared_code == 0
    skipped = QualityReport.model_validate_json(skipped_out.read_text(encoding="utf-8"))
    compared = QualityReport.model_validate_json(compared_out.read_text(encoding="utf-8"))
    assert skipped.performance_baseline_hash is None
    assert compared.performance_baseline_hash == expected_hash
    assert skipped.model_dump(mode="json") != compared.model_dump(mode="json")
