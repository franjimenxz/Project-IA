from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ia_mcp.evals.report import EvalReport, capture_commit, capture_environment
from ia_mcp.observability.redaction import redact
from ia_mcp.performance.models import PerformanceReport, compare_reports

DEFAULT_OUTPUT = Path("build/quality.json")


class ResilienceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    test_count: int
    failed: tuple[str, ...] = ()
    commit: str
    source: str
    outcomes: tuple[str, ...] = ()


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    gate_reason: str
    eval_passed: bool
    resilience_passed: bool
    performance_passed: bool
    production_slo_declared: Literal[False] = False
    commit: str
    dataset_hash: str
    dataset_path: str
    model_provider: str
    model_name: str
    environment: dict[str, str]
    eval_gate_reason: str
    resilience_failures: tuple[str, ...]
    performance_gate_reason: str
    performance_baseline_hash: str | None = None

    def to_markdown(self) -> str:
        lines = [
            "# Quality evidence report",
            "",
            f"- gate: {'PASS' if self.passed else 'FAIL'} ({self.gate_reason})",
            f"- commit: `{self.commit}`",
            f"- dataset: `{self.dataset_path}` hash `{self.dataset_hash}`",
            f"- model: {self.model_provider}/{self.model_name}",
            (
                f"- environment: python {self.environment.get('python', 'unknown')}"
                f" / {self.environment.get('platform', 'unknown')}"
            ),
            "- production_slo: deferred until EXT-007",
            "",
            "## Evidence",
            "",
            f"- eval: {'PASS' if self.eval_passed else 'FAIL'} ({self.eval_gate_reason})",
            (
                f"- resilience: {'PASS' if self.resilience_passed else 'FAIL'} "
                f"failures={len(self.resilience_failures)}"
            ),
            (
                f"- performance: {'PASS' if self.performance_passed else 'FAIL'} "
                f"({self.performance_gate_reason})"
            ),
            "",
        ]
        return redact("\n".join(lines))


def aggregate_quality(
    *,
    eval_report: EvalReport,
    resilience: ResilienceEvidence,
    performance: PerformanceReport,
    performance_baseline: PerformanceReport | None = None,
) -> QualityReport:
    performance_reason = performance.gate_reason
    performance_passed = performance.passed
    baseline_hash: str | None = None
    if performance_baseline is not None:
        comparison = compare_reports(baseline=performance_baseline, current=performance)
        performance_passed = comparison.passed
        performance_reason = (
            "performance_regression" if not comparison.passed else comparison.gate_reason
        )
        baseline_hash = performance_baseline.baseline_hash
    if not eval_report.passed:
        reason = "eval_failed"
        passed = False
    elif not resilience.passed:
        reason = "resilience_failed"
        passed = False
    elif not performance_passed:
        reason = performance_reason
        passed = False
    else:
        reason = "pass"
        passed = True
    return QualityReport(
        passed=passed,
        gate_reason=reason,
        eval_passed=eval_report.passed,
        resilience_passed=resilience.passed,
        performance_passed=performance_passed,
        production_slo_declared=False,
        commit=performance.commit,
        dataset_hash=performance.dataset_hash,
        dataset_path=performance.dataset_path,
        model_provider=performance.model_provider,
        model_name=performance.model_name,
        environment=dict(performance.environment) or capture_environment(),
        eval_gate_reason=eval_report.gate_reason,
        resilience_failures=resilience.failed,
        performance_gate_reason=performance_reason,
        performance_baseline_hash=baseline_hash,
    )


def record_resilience_evidence(
    *,
    passed: bool,
    source: str,
    test_count: int = 0,
    failed: Sequence[str] = (),
    commit: str | None = None,
    outcomes: Sequence[str] = ("retry", "recovery", "manual_review"),
) -> ResilienceEvidence:
    return ResilienceEvidence(
        passed=passed,
        test_count=test_count,
        failed=tuple(failed),
        commit=commit if commit is not None else capture_commit(),
        source=source,
        outcomes=tuple(outcomes),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ia_mcp.evals.quality_report")
    subparsers = parser.add_subparsers(dest="command")
    gate = subparsers.add_parser("gate")
    gate.add_argument("--eval", type=Path, required=True)
    gate.add_argument("--resilience", type=Path, required=True)
    gate.add_argument("--performance", type=Path, required=True)
    gate.add_argument("--baseline", type=Path, default=None)
    gate.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    record = subparsers.add_parser("record-resilience")
    record.add_argument("--source", required=True)
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--test-count", type=int, default=0)
    record.add_argument("--passed", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "gate":
        return _gate(args.eval, args.resilience, args.performance, args.baseline, args.output)
    if args.command == "record-resilience":
        return _record(args.source, args.output, args.test_count, args.passed)
    parser.print_help(sys.stderr)
    return 2


def _gate(
    eval_path: Path,
    resilience_path: Path,
    performance_path: Path,
    baseline_path: Path | None,
    output: Path,
) -> int:
    eval_report = EvalReport.model_validate_json(eval_path.read_text(encoding="utf-8"))
    resilience = ResilienceEvidence.model_validate_json(
        resilience_path.read_text(encoding="utf-8")
    )
    performance = PerformanceReport.model_validate_json(
        performance_path.read_text(encoding="utf-8")
    )
    baseline = None
    if baseline_path is not None and baseline_path.is_file():
        baseline = PerformanceReport.model_validate_json(
            baseline_path.read_text(encoding="utf-8")
        )
    report = aggregate_quality(
        eval_report=eval_report,
        resilience=resilience,
        performance=performance,
        performance_baseline=baseline,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        redact(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)),
        encoding="utf-8",
    )
    markdown_path = output.with_suffix(".md")
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    print(report.to_markdown(), end="")
    return 0 if report.passed else 1


def _record(source: str, output: Path, test_count: int, passed: bool) -> int:
    evidence = record_resilience_evidence(
        passed=passed,
        source=source,
        test_count=test_count,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
