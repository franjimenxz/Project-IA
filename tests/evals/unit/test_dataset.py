import json
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from ia_mcp.evals.models import EvalCase
from ia_mcp.evals.validator import validate_dataset

ROOT = Path(__file__).resolve().parents[3]
MVP_DATASET = ROOT / "evals" / "datasets" / "mvp.jsonl"

REQUIRED_USE_CASES = tuple(f"UC-{index:02d}" for index in range(1, 11))
ADVERSARIAL_TAGS = (
    "insufficient",
    "injection",
    "tool-forbidden",
    "timeout",
    "handoff",
)


def valid_case(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "case_id": "uc-08-tenant-a-hours",
        "tenant_fixture": "tenant_a",
        "config_version": 1,
        "messages": [{"role": "user", "text": "cual es el horario de atencion?"}],
        "allowed_sources": ["kb-a-hours"],
        "forbidden_sources": ["kb-b-hours", "kb-b-coverage"],
        "expected_skill": "faq",
        "allowed_tools": [],
        "forbidden_tools": ["appointments.create"],
        "expected_workflow_state": None,
        "expected_outcome": "answer",
        "assertions": [{"name": "grounded"}, {"name": "no_cross_tenant"}],
    }
    payload.update(overrides)
    return payload


def write_dataset(path: Path, cases: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    return path


def mvp_cases() -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line in MVP_DATASET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(EvalCase.model_validate(json.loads(line)))
    return cases


def test_duplicate_case_id_fails_validation(tmp_path: Path) -> None:
    dataset = write_dataset(
        tmp_path / "dup.jsonl",
        [
            valid_case(),
            valid_case(allowed_sources=["kb-a-coverage"]),
        ],
    )

    report = validate_dataset(dataset)

    assert report.valid is False
    assert any("duplicate_case_id" in issue for issue in report.issues)


def test_allowed_forbidden_source_overlap_fails_validation(tmp_path: Path) -> None:
    dataset = write_dataset(
        tmp_path / "overlap.jsonl",
        [
            valid_case(
                allowed_sources=["kb-a-hours", "kb-b-hours"],
                forbidden_sources=["kb-b-hours"],
            )
        ],
    )

    report = validate_dataset(dataset)

    assert report.valid is False
    assert any("source_overlap" in issue for issue in report.issues)


def test_allowed_forbidden_tool_overlap_fails_validation(tmp_path: Path) -> None:
    dataset = write_dataset(
        tmp_path / "tool-overlap.jsonl",
        [
            valid_case(
                expected_skill="appointments",
                allowed_tools=["appointments.search"],
                forbidden_tools=["appointments.search", "appointments.create"],
                allowed_sources=[],
                expected_outcome="completed",
                expected_workflow_state="completed",
            )
        ],
    )

    report = validate_dataset(dataset)

    assert report.valid is False
    assert any("tool_overlap" in issue for issue in report.issues)


def test_unknown_source_reference_fails_validation(tmp_path: Path) -> None:
    dataset = write_dataset(
        tmp_path / "unknown-source.jsonl",
        [valid_case(allowed_sources=["kb-unknown-doc"])],
    )

    report = validate_dataset(dataset)

    assert report.valid is False
    assert any("unknown_source" in issue for issue in report.issues)


def test_source_ids_are_checked_against_external_catalog(tmp_path: Path) -> None:
    catalog = tmp_path / "known_sources.json"
    catalog.write_text(json.dumps({"source_ids": ["kb-a-hours"]}), encoding="utf-8")
    dataset = write_dataset(
        tmp_path / "catalog.jsonl",
        [valid_case(forbidden_sources=["kb-b-hours"])],
    )

    report = validate_dataset(dataset, source_catalog=catalog)

    assert report.valid is False
    assert any(
        "unknown_source" in issue and "kb-b-hours" in issue for issue in report.issues
    )


def test_all_single_turn_dataset_fails_validation(tmp_path: Path) -> None:
    dataset = write_dataset(tmp_path / "single.jsonl", [valid_case()])

    report = validate_dataset(dataset)

    assert report.valid is False
    assert any("missing_multi_turn" in issue for issue in report.issues)


def test_eval_message_allows_assistant_role() -> None:
    case = EvalCase.model_validate(
        valid_case(
            expected_skill="appointments",
            allowed_sources=[],
            expected_outcome="clarify",
            expected_workflow_state="collecting",
            messages=[
                {"role": "user", "text": "quiero un turno pa cardiologia"},
                {"role": "assistant", "text": "¿Para qué fechas buscamos?"},
                {"role": "user", "text": "la semana que viene"},
            ],
        )
    )

    assert len(case.messages) == 3
    assert case.messages[1].role == "assistant"


def test_eval_case_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        EvalCase.model_validate({**valid_case(), "completion": "real model output"})


def test_source_catalog_is_independent_allowlist() -> None:
    catalog = json.loads(
        (ROOT / "evals" / "fixtures" / "known_sources.json").read_text(encoding="utf-8")
    )
    catalog_ids = frozenset(catalog["source_ids"])
    used: set[str] = set()
    for case in mvp_cases():
        used |= set(case.allowed_sources) | set(case.forbidden_sources)
    assert used <= catalog_ids
    assert catalog_ids - used


def test_mvp_dataset_is_valid_and_hashed() -> None:
    report = validate_dataset(MVP_DATASET)

    assert report.valid is True
    assert report.issues == ()
    assert report.case_count >= 15
    assert report.dataset_hash == sha256(MVP_DATASET.read_bytes()).hexdigest()
    assert len(report.dataset_hash) == 64


def test_mvp_dataset_covers_use_cases_tenants_and_adversarial() -> None:
    report = validate_dataset(MVP_DATASET)

    for use_case in REQUIRED_USE_CASES:
        assert report.use_case_counts.get(use_case, 0) >= 1
    assert report.tenant_counts.get("tenant_a", 0) >= 1
    assert report.tenant_counts.get("tenant_b", 0) >= 1
    for tag in ADVERSARIAL_TAGS:
        assert report.adversarial_counts.get(tag, 0) >= 1


def test_mvp_dataset_includes_multi_turn_conversation() -> None:
    assert any(len(case.messages) >= 2 for case in mvp_cases())


def test_mvp_use_cases_match_expected_skills_and_tools() -> None:
    by_uc: dict[str, list[EvalCase]] = {}
    for case in mvp_cases():
        by_uc.setdefault(f"UC-{case.case_id[3:5]}", []).append(case)

    assert any(case.expected_skill == "faq" for case in by_uc["UC-01"])
    assert any(
        case.expected_skill == "appointments"
        and case.expected_workflow_state == "collecting"
        for case in by_uc["UC-02"]
    )
    assert any("appointments.search" in case.allowed_tools for case in by_uc["UC-03"])
    assert any("appointments.create" in case.allowed_tools for case in by_uc["UC-04"])
    assert any("appointments.cancel" in case.allowed_tools for case in by_uc["UC-05"])
    assert any("appointments.reschedule" in case.allowed_tools for case in by_uc["UC-06"])
    assert any("appointments.confirm" in case.allowed_tools for case in by_uc["UC-07"])
    assert any(case.expected_skill == "faq" for case in by_uc["UC-08"])
    assert any(case.expected_skill == "human_handoff" for case in by_uc["UC-09"])


def test_mvp_uc10_is_scheduler_reminder_not_patient_confirm() -> None:
    reminder_assertions = {
        "reminder_dispatched",
        "reminder_skipped",
        "reminder_deduped",
    }
    uc10 = [case for case in mvp_cases() if case.case_id.startswith("uc-10-")]
    assert uc10
    seen: set[str] = set()
    for case in uc10:
        blob = " ".join(message.text.lower() for message in case.messages)
        names = {assertion.name for assertion in case.assertions}
        assert case.expected_skill == "appointments"
        assert "appointments.get" in case.allowed_tools
        assert "appointments.confirm" not in case.allowed_tools
        assert "confirmo" not in blob
        assert names & reminder_assertions
        seen |= names & reminder_assertions
    assert "reminder_dispatched" in seen
    assert "reminder_skipped" in seen
    assert "reminder_deduped" in seen


def test_mvp_dataset_lines_are_eval_cases_without_completions() -> None:
    raw = MVP_DATASET.read_text(encoding="utf-8").strip().splitlines()
    assert raw
    seen: set[str] = set()
    for line in raw:
        payload = json.loads(line)
        assert "completion" not in payload
        assert "prompt" not in payload
        case = EvalCase.model_validate(payload)
        assert case.case_id not in seen
        seen.add(case.case_id)
        assert case.allowed_sources.isdisjoint(case.forbidden_sources)
        assert case.allowed_tools.isdisjoint(case.forbidden_tools)
        assert {message.role for message in case.messages} <= {"user", "assistant"}
        assert any(message.role == "user" or message.role == "assistant" for message in case.messages)
