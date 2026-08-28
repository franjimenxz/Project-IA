from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ia_mcp.performance.models import (
    PerformanceReport,
    compare_reports,
    report_to_json,
    report_to_markdown,
)
from ia_mcp.performance.scenarios import SCENARIO_NAMES, run_scenario

DEFAULT_OUTPUT = Path("build/performance.json")
DEFAULT_BASELINE = Path("evals/baselines/mvp-performance.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ia_mcp.performance")
    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--scenario", required=True)
    run_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run_parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--current", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "run":
        return _run(args.scenario, args.output, args.baseline)
    if args.command == "compare":
        return _compare(args.baseline, args.current)
    parser.print_help(sys.stderr)
    return 2


def _run(scenario: str, output: Path, baseline: Path) -> int:
    if scenario not in SCENARIO_NAMES:
        print(f"unknown scenario: {scenario}", file=sys.stderr)
        return 2
    try:
        report = run_scenario(scenario)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report_to_json(report), encoding="utf-8")
    markdown_path = output.with_suffix(".md")
    markdown_path.write_text(report_to_markdown(report), encoding="utf-8")
    print(report_to_markdown(report), end="")
    if not report.passed:
        return 1
    baseline_text = _read_required(baseline)
    if baseline_text is None:
        print(f"missing baseline: {baseline}", file=sys.stderr)
        return 1
    comparison = compare_reports(
        baseline=PerformanceReport.model_validate_json(baseline_text),
        current=report,
    )
    print(f"baseline_compare: {'PASS' if comparison.passed else 'FAIL'} ({comparison.gate_reason})")
    return 0 if comparison.passed else 1


def _compare(baseline: Path, current: Path) -> int:
    baseline_text = _read_required(baseline)
    current_text = _read_required(current)
    if baseline_text is None:
        print(f"missing baseline: {baseline}", file=sys.stderr)
        return 1
    if current_text is None:
        print(f"missing current report: {current}", file=sys.stderr)
        return 1
    comparison = compare_reports(
        baseline=PerformanceReport.model_validate_json(baseline_text),
        current=PerformanceReport.model_validate_json(current_text),
    )
    payload = {
        "passed": comparison.passed,
        "gate_reason": comparison.gate_reason,
        "regressions": [item.model_dump(mode="json") for item in comparison.regressions],
        "budget_failures": list(comparison.budget_failures),
        "provenance_failures": list(comparison.provenance_failures),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if comparison.passed else 1


def _read_required(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
