import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

from pydantic import ValidationError

from ia_mcp.evals.models import (
    ADVERSARIAL_TAGS,
    KNOWN_SOURCE_IDS,
    DatasetValidationReport,
    EvalCase,
)
from ia_mcp.mcp.registry import KNOWN_TOOLS

_REQUIRED_USE_CASES = tuple(f"UC-{index:02d}" for index in range(1, 11))
_KNOWN_TOOL_NAMES = frozenset(str(name) for name in KNOWN_TOOLS)


def validate_dataset(path: Path) -> DatasetValidationReport:
    payload = path.read_bytes()
    dataset_hash = sha256(payload).hexdigest()
    issues: list[str] = []
    cases: list[EvalCase] = []
    id_counts: Counter[str] = Counter()

    lines = [line for line in payload.decode("utf-8").splitlines() if line.strip()]
    if not lines:
        issues.append("empty_dataset")

    for index, line in enumerate(lines, start=1):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            issues.append(f"schema:line-{index}:invalid_json")
            continue
        if not isinstance(raw, dict):
            issues.append(f"schema:line-{index}:not_object")
            continue
        case_id = str(raw.get("case_id", f"line-{index}"))
        try:
            case = EvalCase.model_validate(raw)
        except ValidationError:
            issues.append(f"schema:{case_id}")
            continue
        cases.append(case)
        id_counts[case.case_id] += 1
        issues.extend(_case_issues(case))

    for case_id, count in sorted(id_counts.items()):
        if count > 1:
            issues.append(f"duplicate_case_id:{case_id}")

    use_case_counts = _use_case_counts(cases)
    tenant_counts = _tenant_counts(cases)
    adversarial_counts = _adversarial_counts(cases)
    if cases:
        issues.extend(_coverage_issues(use_case_counts, tenant_counts, adversarial_counts))

    return DatasetValidationReport(
        valid=not issues,
        case_count=len(cases),
        dataset_hash=dataset_hash,
        issues=tuple(issues),
        use_case_counts=use_case_counts,
        tenant_counts=tenant_counts,
        adversarial_counts=adversarial_counts,
    )


def _case_issues(case: EvalCase) -> list[str]:
    issues: list[str] = []
    if not case.allowed_sources.isdisjoint(case.forbidden_sources):
        issues.append(f"source_overlap:{case.case_id}")
    if not case.allowed_tools.isdisjoint(case.forbidden_tools):
        issues.append(f"tool_overlap:{case.case_id}")
    unknown_sources = (case.allowed_sources | case.forbidden_sources) - KNOWN_SOURCE_IDS
    for source in sorted(unknown_sources):
        issues.append(f"unknown_source:{case.case_id}:{source}")
    unknown_tools = (case.allowed_tools | case.forbidden_tools) - _KNOWN_TOOL_NAMES
    for tool in sorted(unknown_tools):
        issues.append(f"unknown_tool:{case.case_id}:{tool}")
    return issues


def _use_case_counts(cases: list[EvalCase]) -> dict[str, int]:
    counts = {use_case: 0 for use_case in _REQUIRED_USE_CASES}
    for case in cases:
        counts[f"UC-{case.case_id[3:5]}"] += 1
    return counts


def _tenant_counts(cases: list[EvalCase]) -> dict[str, int]:
    counts = {"tenant_a": 0, "tenant_b": 0}
    for case in cases:
        counts[case.tenant_fixture] += 1
    return counts


def _adversarial_counts(cases: list[EvalCase]) -> dict[str, int]:
    counts = {tag: 0 for tag in ADVERSARIAL_TAGS}
    for case in cases:
        for tag in ADVERSARIAL_TAGS:
            if tag in case.case_id:
                counts[tag] += 1
    return counts


def _coverage_issues(
    use_case_counts: dict[str, int],
    tenant_counts: dict[str, int],
    adversarial_counts: dict[str, int],
) -> list[str]:
    issues: list[str] = []
    for use_case, count in use_case_counts.items():
        if count < 1:
            issues.append(f"missing_use_case:{use_case}")
    for tenant, count in tenant_counts.items():
        if count < 1:
            issues.append(f"missing_tenant:{tenant}")
    for tag, count in adversarial_counts.items():
        if count < 1:
            issues.append(f"missing_adversarial:{tag}")
    return issues
