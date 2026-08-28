from __future__ import annotations

import json
import platform
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ia_mcp.evals.scorers import SCORE_CATEGORIES, TrajectoryScore
from ia_mcp.observability.redaction import redact

# Fake/smoke gate thresholds (TDD-P06). Tenant, tools, sources, policy and
# workflow are 100%. Skill, outcome and groundedness are also 1.0 for fake so
# a capability collapse cannot hide behind a high average. Real-model evals
# replace skill/groundedness with an approved baseline before production.
CATEGORY_THRESHOLDS: dict[str, float] = {
    "tenant": 1.0,
    "tools": 1.0,
    "sources": 1.0,
    "policy": 1.0,
    "workflow": 1.0,
    "outcome": 1.0,
    "skill": 1.0,
    "groundedness": 1.0,
}

_PRIVATE_KEYS = frozenset(
    {
        "prompt",
        "reasoning",
        "private_reasoning",
        "completion",
        "core_instructions",
        "instructions",
    }
)
_PRIVATE_VALUE_TOKENS: tuple[str, ...] = (
    "prompt",
    "reasoning",
    "private_reasoning",
    "completion",
    "core_instructions",
)


class CategoryRegression(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline: float
    current: float


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    commit: str
    dataset_hash: str
    dataset_path: str
    model_provider: str
    model_name: str
    config_summary: dict[str, object]
    environment: dict[str, str]
    category_averages: dict[str, float]
    critical_failures: tuple[str, ...]
    case_results: tuple[TrajectoryScore, ...]
    flakiness: dict[str, int] = Field(default_factory=dict)
    gate_reason: str = "pass"


class ComparisonReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    regressions: dict[str, CategoryRegression]
    critical_failures: tuple[str, ...]
    gate_reason: str
    missing_cases: tuple[str, ...] = ()
    provenance_failures: tuple[str, ...] = ()


def capture_environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }


def capture_commit(repo: Path | None = None) -> str:
    cwd = repo if repo is not None else Path.cwd()
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def build_report(
    scores: tuple[TrajectoryScore, ...],
    *,
    dataset_path: str,
    dataset_hash: str,
    model_provider: str,
    model_name: str,
    config_summary: Mapping[str, object],
    commit: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> EvalReport:
    averages = _averages(scores)
    critical_failures = tuple(
        f"{score.case_id}:{failure}"
        for score in scores
        for failure in score.critical_failures
    )
    critical_override = any(score.critical and not score.passed for score in scores)
    below_threshold = tuple(
        name
        for name, threshold in CATEGORY_THRESHOLDS.items()
        if averages.get(name, 0.0) < threshold
    )
    passed = not critical_failures and not critical_override and not below_threshold
    if critical_failures:
        reason = "critical_failure"
    elif critical_override:
        reason = "critical_case_failed"
    elif below_threshold:
        reason = "threshold:" + ",".join(below_threshold)
    else:
        reason = "pass"
    return EvalReport(
        passed=passed,
        commit=commit if commit is not None else capture_commit(),
        dataset_hash=dataset_hash,
        dataset_path=dataset_path,
        model_provider=model_provider,
        model_name=model_name,
        config_summary=dict(config_summary),
        environment=dict(environment) if environment is not None else capture_environment(),
        category_averages=averages,
        critical_failures=critical_failures,
        case_results=scores,
        flakiness={},
        gate_reason=reason,
    )


def compare_reports(*, baseline: EvalReport, current: EvalReport) -> ComparisonReport:
    regressions: dict[str, CategoryRegression] = {}
    categories = dict.fromkeys([*baseline.category_averages, *current.category_averages])
    for name in categories:
        base_value = baseline.category_averages.get(name, 0.0)
        current_value = current.category_averages.get(name, 0.0)
        if current_value < base_value:
            regressions[name] = CategoryRegression(baseline=base_value, current=current_value)
    baseline_ids = tuple(dict.fromkeys(score.case_id for score in baseline.case_results))
    current_ids = {score.case_id for score in current.case_results}
    missing_cases = tuple(case_id for case_id in baseline_ids if case_id not in current_ids)
    provenance: list[str] = []
    if baseline.dataset_hash != current.dataset_hash:
        provenance.append("dataset_hash")
    if (baseline.model_provider, baseline.model_name) != (
        current.model_provider,
        current.model_name,
    ):
        provenance.append("model")
    provenance_failures = tuple(provenance)
    critical = current.critical_failures
    if provenance_failures:
        reason = f"{provenance_failures[0]}_mismatch"
        passed = False
    elif missing_cases:
        reason = "missing_cases"
        passed = False
    elif regressions:
        reason = "category_regression"
        passed = False
    elif critical:
        reason = "critical_failure"
        passed = False
    else:
        reason = "pass"
        passed = True
    return ComparisonReport(
        passed=passed,
        regressions=regressions,
        critical_failures=critical,
        gate_reason=reason,
        missing_cases=missing_cases,
        provenance_failures=provenance_failures,
    )


def report_to_json(report: EvalReport) -> str:
    payload = report.model_dump(mode="json")
    _reject_private(payload)
    return redact(json.dumps(payload, indent=2, sort_keys=True))


def report_to_markdown(report: EvalReport) -> str:
    lines = [
        "# Eval report",
        "",
        f"- gate: {'PASS' if report.passed else 'FAIL'} ({report.gate_reason})",
        f"- commit: `{report.commit}`",
        f"- dataset: `{report.dataset_path}` hash `{report.dataset_hash}`",
        f"- model: {report.model_provider}/{report.model_name}",
        f"- config: `{json.dumps(report.config_summary, sort_keys=True)}`",
        (
            f"- environment: python {report.environment.get('python', 'unknown')}"
            f" / {report.environment.get('platform', 'unknown')}"
        ),
        "",
        "## Category averages",
        "",
    ]
    for name in SCORE_CATEGORIES:
        if name in report.category_averages:
            lines.append(f"- {name}: {report.category_averages[name]:.3f}")
    lines.extend(["", "## Critical failures", ""])
    if report.critical_failures:
        for failure in report.critical_failures:
            lines.append(f"- {failure}")
    else:
        lines.append("- none")
    lines.extend(["", "## Cases", ""])
    for score in report.case_results:
        status = "pass" if score.passed else "fail"
        lines.append(f"- {score.case_id}: {status} critical={str(score.critical).lower()}")
    text = "\n".join(lines) + "\n"
    _reject_private_text(text)
    return redact(text)


def write_report(report: EvalReport, json_path: Path, markdown_path: Path | None = None) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(report_to_json(report), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(report_to_markdown(report), encoding="utf-8")


def _averages(scores: tuple[TrajectoryScore, ...]) -> dict[str, float]:
    if not scores:
        return {name: 0.0 for name in SCORE_CATEGORIES}
    totals = {name: 0.0 for name in SCORE_CATEGORIES}
    for score in scores:
        for name in SCORE_CATEGORIES:
            totals[name] += score.category_scores.get(name, 0.0)
    count = float(len(scores))
    return {name: totals[name] / count for name in SCORE_CATEGORIES}


def _reject_private(payload: object) -> None:
    if isinstance(payload, dict):
        leaked = _PRIVATE_KEYS.intersection(payload)
        if leaked:
            raise ValueError("private eval fields are forbidden")
        for value in payload.values():
            _reject_private(value)
        return
    if isinstance(payload, list | tuple):
        for item in payload:
            _reject_private(item)
        return
    if isinstance(payload, str):
        _reject_private_text(payload)


def _reject_private_text(text: str) -> None:
    lowered = text.lower()
    for key in _PRIVATE_KEYS:
        if f'"{key}"' in lowered:
            raise ValueError("private eval fields are forbidden")
    for token in _PRIVATE_VALUE_TOKENS:
        if token in lowered:
            raise ValueError("private eval fields are forbidden")
