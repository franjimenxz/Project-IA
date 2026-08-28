import json
from pathlib import Path

from ia_mcp.evals.cli import main
from ia_mcp.evals.report import (
    build_report,
    capture_environment,
    report_to_json,
    report_to_markdown,
)
from ia_mcp.evals.scorers import TrajectoryScore
from tests.evals.unit.test_report import _report


def _score(*, passed: bool = True, tools: float = 1.0) -> TrajectoryScore:
    return TrajectoryScore(
        case_id="uc-08-tenant-a-hours",
        passed=passed,
        critical=True,
        critical_failures=() if passed else ("forbidden_tool:appointments.create",),
        category_scores={
            "tenant": 1.0,
            "skill": 1.0,
            "sources": 1.0,
            "tools": tools,
            "workflow": 1.0,
            "outcome": 1.0,
            "groundedness": 1.0,
            "policy": 1.0 if passed else 0.0,
        },
    )


def test_report_reproduces_commit_dataset_model_and_environment() -> None:
    report = build_report(
        (_score(),),
        dataset_path="evals/datasets/mvp.jsonl",
        dataset_hash="a" * 64,
        model_provider="fake",
        model_name="fake-llm",
        config_summary={"suite": "smoke", "config_version": 1},
        commit="deadbeef",
        environment={"python": "3.13.12", "platform": "darwin"},
    )
    markdown = report_to_markdown(report)
    payload = json.loads(report_to_json(report))
    assert report.commit == "deadbeef"
    assert report.dataset_hash == "a" * 64
    assert report.model_provider == "fake"
    assert report.model_name == "fake-llm"
    assert report.config_summary["suite"] == "smoke"
    assert report.environment["python"] == "3.13.12"
    assert "deadbeef" in markdown
    assert "evals/datasets/mvp.jsonl" in markdown
    assert payload["commit"] == "deadbeef"
    assert "prompt" not in payload
    assert "reasoning" not in payload
    env = capture_environment()
    assert "python" in env
    assert "platform" in env


def test_compare_cli_exits_nonzero_on_regression(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    baseline.write_text(report_to_json(_report(tools=1.0)), encoding="utf-8")
    current.write_text(report_to_json(_report(tools=0.4)), encoding="utf-8")

    code = main(["compare", "--baseline", str(baseline), "--current", str(current)])

    assert code == 1


def test_compare_cli_passes_when_current_matches_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    payload = report_to_json(_report(tools=1.0))
    baseline.write_text(payload, encoding="utf-8")
    current.write_text(payload, encoding="utf-8")

    code = main(["compare", "--baseline", str(baseline), "--current", str(current)])

    assert code == 0


def test_validate_cli_still_accepts_mvp_dataset() -> None:
    code = main(["validate", "evals/datasets/mvp.jsonl"])
    assert code == 0
