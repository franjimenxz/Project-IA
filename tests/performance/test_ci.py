from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_quality_evidence_workflow_gates_on_pull_request() -> None:
    text = (ROOT / ".github/workflows/quality-evidence.yml").read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert "types: [published]" not in text
    assert "schedule:" in text
    assert "workflow_dispatch:" in text
    assert "tests/performance" in text
    assert "tests/evals/unit" in text


def test_pr_quality_workflow_runs_performance_and_eval_unit_tests() -> None:
    text = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "tests/performance" in text
    assert "tests/evals/unit" in text
