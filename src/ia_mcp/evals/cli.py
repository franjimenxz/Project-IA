from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from ia_mcp.evals.report import (
    ComparisonReport,
    EvalReport,
    build_report,
    compare_reports,
    report_to_markdown,
    write_report,
)
from ia_mcp.evals.runner import EvalRunner, load_eval_cases, select_suite
from ia_mcp.evals.scorers import score_trajectory
from ia_mcp.evals.validator import validate_dataset

DEFAULT_DATASET = Path("evals/datasets/mvp.jsonl")
DEFAULT_OUTPUT = Path("build/evals.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ia_mcp.evals")
    subparsers = parser.add_subparsers(dest="command")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("dataset", type=Path)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--suite", required=True)
    run_parser.add_argument("--provider", required=True)
    run_parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    run_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--baseline", type=Path, required=True)
    compare_parser.add_argument("--current", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "validate":
        return _validate(args.dataset)
    if args.command == "run":
        return _run(args.suite, args.provider, args.dataset, args.output)
    if args.command == "compare":
        return _compare(args.baseline, args.current)
    parser.print_help(sys.stderr)
    return 2


def _validate(dataset: Path) -> int:
    report = validate_dataset(dataset)
    print(
        f"valid={str(report.valid).lower()} cases={report.case_count} "
        f"hash={report.dataset_hash}"
    )
    print(
        "use_cases="
        + ",".join(f"{name}:{count}" for name, count in sorted(report.use_case_counts.items()))
    )
    print(
        "tenants="
        + ",".join(f"{name}:{count}" for name, count in sorted(report.tenant_counts.items()))
    )
    print(
        "adversarial="
        + ",".join(
            f"{name}:{count}" for name, count in sorted(report.adversarial_counts.items())
        )
    )
    for issue in report.issues:
        print(issue, file=sys.stderr)
    return 0 if report.valid else 1


def _run(suite: str, provider: str, dataset: Path, output: Path) -> int:
    if provider != "fake":
        print("only --provider fake is supported", file=sys.stderr)
        return 2
    try:
        cases = select_suite(load_eval_cases(dataset), suite)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    validation = validate_dataset(dataset)
    runner = EvalRunner.for_fake_provider()
    trajectories = asyncio.run(runner.run_suite(cases))
    scores = tuple(
        score_trajectory(case, observed)
        for case, observed in zip(cases, trajectories, strict=True)
    )
    report = build_report(
        scores,
        dataset_path=str(dataset),
        dataset_hash=validation.dataset_hash,
        model_provider=provider,
        model_name="fake-llm",
        config_summary={"suite": suite, "config_version": 1},
    )
    markdown_path = output.with_suffix(".md")
    write_report(report, output, markdown_path)
    print(report_to_markdown(report), end="")
    return 0 if report.passed else 1


def _compare(baseline: Path, current: Path) -> int:
    comparison = compare_reports(
        baseline=EvalReport.model_validate_json(baseline.read_text(encoding="utf-8")),
        current=EvalReport.model_validate_json(current.read_text(encoding="utf-8")),
    )
    print(_comparison_text(comparison), end="")
    return 0 if comparison.passed else 1


def _comparison_text(comparison: ComparisonReport) -> str:
    lines = [
        f"gate={'PASS' if comparison.passed else 'FAIL'} ({comparison.gate_reason})",
    ]
    if comparison.regressions:
        lines.append("regressions:")
        for name, delta in sorted(comparison.regressions.items()):
            lines.append(f"  {name}: {delta.baseline:.3f} -> {delta.current:.3f}")
    else:
        lines.append("regressions: none")
    if comparison.critical_failures:
        lines.append("critical_failures:")
        for failure in comparison.critical_failures:
            lines.append(f"  {failure}")
    else:
        lines.append("critical_failures: none")
    if comparison.missing_cases:
        lines.append("missing_cases:")
        for case_id in comparison.missing_cases:
            lines.append(f"  {case_id}")
    else:
        lines.append("missing_cases: none")
    if comparison.provenance_failures:
        lines.append(
            "provenance_failures: " + ",".join(comparison.provenance_failures)
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
