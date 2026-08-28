from pathlib import Path

from ia_mcp.performance.cli import main
from ia_mcp.performance.models import PerformanceReport
from ia_mcp.performance.scenarios import SCENARIO_NAMES, run_scenario


def test_unknown_scenario_is_rejected() -> None:
    code = main(["run", "--scenario", "not-a-scenario"])
    assert code == 2


def test_mvp_baseline_is_a_known_scenario() -> None:
    assert "mvp-baseline" in SCENARIO_NAMES


def test_mvp_baseline_report_includes_latency_throughput_errors_and_queue() -> None:
    report = run_scenario("mvp-baseline")
    assert report.scenario == "mvp-baseline"
    assert report.latency_by_span
    assert "knowledge.search" in report.latency_by_span
    assert "llm.generate" in report.latency_by_span
    assert "workflow.advance" in report.latency_by_span
    assert "scheduler.dispatch" in report.latency_by_span
    assert report.throughput.completed > 0
    assert report.throughput.operations_per_second > 0
    assert report.errors.count == 0
    assert report.queue_age.depth > 0
    assert report.production_slo_declared is False
    assert report.commit
    assert report.dataset_hash
    assert report.model_provider == "fake"
    assert "config_version" in report.config_summary
    assert "python" in report.environment
    assert report.passed is True


def test_cli_run_mvp_baseline_writes_report_and_exits_zero(tmp_path: Path) -> None:
    output = tmp_path / "performance.json"
    code = main(["run", "--scenario", "mvp-baseline", "--output", str(output)])
    assert code == 0
    assert output.is_file()
    report = PerformanceReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert report.scenario == "mvp-baseline"
    assert report.latency_by_span
    assert report.errors.count == 0
    assert report.queue_age.depth > 0
    assert report.production_slo_declared is False


def test_cli_compare_fails_on_latency_regression(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    report = run_scenario("mvp-baseline")
    worse = report.model_copy(
        update={
            "latency_by_span": {
                name: item.model_copy(update={"p95_ms": item.p95_ms + 50.0})
                for name, item in report.latency_by_span.items()
            }
        }
    )
    baseline.write_text(report.model_dump_json(), encoding="utf-8")
    current.write_text(worse.model_dump_json(), encoding="utf-8")
    code = main(["compare", "--baseline", str(baseline), "--current", str(current)])
    assert code == 1
