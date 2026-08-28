from ia_mcp.evals.report import (
    CATEGORY_THRESHOLDS,
    EvalReport,
    build_report,
    compare_reports,
    report_to_json,
    report_to_markdown,
)
from ia_mcp.evals.scorers import TrajectoryScore


def _passing_score(case_id: str = "uc-08-tenant-a-hours") -> TrajectoryScore:
    return TrajectoryScore(
        case_id=case_id,
        passed=True,
        critical=True,
        critical_failures=(),
        category_scores={name: 1.0 for name in CATEGORY_THRESHOLDS},
    )


def _report(
    *,
    tools: float = 1.0,
    tenant: float = 1.0,
    dataset_hash: str = "d" * 64,
    model_name: str = "fake-llm",
    model_provider: str = "fake",
    case_ids: tuple[str, ...] = (),
) -> EvalReport:
    scores = {name: 1.0 for name in CATEGORY_THRESHOLDS}
    scores["tools"] = tools
    scores["tenant"] = tenant
    case_results = tuple(
        TrajectoryScore(
            case_id=case_id,
            passed=True,
            critical=True,
            critical_failures=(),
            category_scores=dict(scores),
        )
        for case_id in case_ids
    )
    return EvalReport.model_validate(
        {
            "passed": tools >= 1.0 and tenant >= 1.0,
            "commit": "abc123",
            "dataset_hash": dataset_hash,
            "dataset_path": "evals/datasets/mvp.jsonl",
            "model_provider": model_provider,
            "model_name": model_name,
            "config_summary": {"suite": "smoke", "config_version": 1},
            "environment": {"python": "3.13.12", "platform": "test"},
            "category_averages": scores,
            "critical_failures": (),
            "case_results": case_results,
            "flakiness": {},
        }
    )


def test_baseline_regression_is_reported_by_category() -> None:
    comparison = compare_reports(
        baseline=_report(tools=1.0),
        current=_report(tools=0.5),
    )
    assert comparison.passed is False
    assert "tools" in comparison.regressions
    assert comparison.regressions["tools"].baseline == 1.0
    assert comparison.regressions["tools"].current == 0.5


def test_matching_baseline_does_not_regress() -> None:
    comparison = compare_reports(
        baseline=_report(tools=1.0),
        current=_report(tools=1.0),
    )
    assert comparison.passed is True
    assert comparison.regressions == {}


def test_critical_failure_fails_gate_despite_high_averages() -> None:
    passing = TrajectoryScore(
        case_id="uc-08-tenant-a-hours",
        passed=True,
        critical=True,
        critical_failures=(),
        category_scores={
            "tenant": 1.0,
            "skill": 1.0,
            "sources": 1.0,
            "tools": 1.0,
            "workflow": 1.0,
            "outcome": 1.0,
            "groundedness": 1.0,
            "policy": 1.0,
        },
    )
    failing = TrajectoryScore(
        case_id="uc-08-tenant-a-tool-forbidden",
        passed=False,
        critical=True,
        critical_failures=("forbidden_tool:appointments.create",),
        category_scores={
            "tenant": 1.0,
            "skill": 1.0,
            "sources": 1.0,
            "tools": 0.0,
            "workflow": 1.0,
            "outcome": 1.0,
            "groundedness": 1.0,
            "policy": 0.0,
        },
    )
    report = build_report(
        (passing, passing, passing, passing, failing),
        dataset_path="evals/datasets/mvp.jsonl",
        dataset_hash="b" * 64,
        model_provider="fake",
        model_name="fake-llm",
        config_summary={"suite": "smoke"},
        commit="abc123",
        environment={"python": "3.13.12", "platform": "test"},
    )
    assert report.category_averages["skill"] == 1.0
    assert report.category_averages["groundedness"] == 1.0
    assert report.passed is False
    assert report.gate_reason == "critical_failure"
    assert "uc-08-tenant-a-tool-forbidden:forbidden_tool:appointments.create" in (
        report.critical_failures
    )


def _build(
    scores: tuple[TrajectoryScore, ...],
    *,
    config_summary: dict[str, object] | None = None,
) -> EvalReport:
    return build_report(
        scores,
        dataset_path="evals/datasets/mvp.jsonl",
        dataset_hash="b" * 64,
        model_provider="fake",
        model_name="fake-llm",
        config_summary=config_summary or {"suite": "smoke"},
        commit="abc123",
        environment={"python": "3.13.12", "platform": "test"},
    )


def test_category_thresholds_are_explicit_and_load_bearing() -> None:
    assert CATEGORY_THRESHOLDS["tenant"] == 1.0
    assert CATEGORY_THRESHOLDS["tools"] == 1.0
    assert CATEGORY_THRESHOLDS["sources"] == 1.0
    assert CATEGORY_THRESHOLDS["policy"] == 1.0
    assert CATEGORY_THRESHOLDS["workflow"] == 1.0
    assert CATEGORY_THRESHOLDS["outcome"] == 1.0
    assert CATEGORY_THRESHOLDS["skill"] == 1.0
    assert CATEGORY_THRESHOLDS["groundedness"] == 1.0
    collapsed = TrajectoryScore(
        case_id="uc-08-tenant-a-hours",
        passed=True,
        critical=True,
        critical_failures=(),
        category_scores={
            "tenant": 1.0,
            "skill": 0.0,
            "sources": 1.0,
            "tools": 1.0,
            "workflow": 1.0,
            "outcome": 0.0,
            "groundedness": 0.0,
            "policy": 1.0,
        },
    )
    report = _build((collapsed, collapsed))
    assert report.passed is False
    assert report.gate_reason != "pass"


def test_capability_collapse_to_insufficient_fails_gate() -> None:
    collapsed = TrajectoryScore(
        case_id="uc-08-tenant-a-hours",
        passed=True,
        critical=False,
        critical_failures=(),
        category_scores={
            "tenant": 1.0,
            "skill": 1.0,
            "sources": 1.0,
            "tools": 1.0,
            "workflow": 1.0,
            "outcome": 0.0,
            "groundedness": 0.0,
            "policy": 1.0,
        },
    )
    report = _build((collapsed, collapsed, collapsed))
    json_text = report_to_json(report)
    markdown = report_to_markdown(report)
    assert report.passed is False
    assert report.category_averages["outcome"] == 0.0
    assert '"passed": false' in json_text or '"passed":false' in json_text.replace(" ", "")
    assert "FAIL" in markdown


def test_serialized_reports_must_not_contain_private_tokens_in_strings() -> None:
    report = _build((_passing_score(),))
    json_text = report_to_json(report)
    markdown = report_to_markdown(report)
    for token in ("prompt", "reasoning", "completion", "core_instructions"):
        assert token not in json_text
        assert token not in markdown


def test_config_summary_values_cannot_carry_private_tokens() -> None:
    report = _build(
        (_passing_score(),),
        config_summary={"note": "leaked core_instructions from a prompt completion"},
    )
    json_text = ""
    markdown = ""
    json_error: Exception | None = None
    markdown_error: Exception | None = None
    try:
        json_text = report_to_json(report)
    except ValueError as exc:
        json_error = exc
    try:
        markdown = report_to_markdown(report)
    except ValueError as exc:
        markdown_error = exc
    if json_error is None:
        assert "core_instructions" not in json_text
        assert "prompt" not in json_text
        assert "completion" not in json_text
    if markdown_error is None:
        assert "core_instructions" not in markdown
        assert "prompt" not in markdown
    assert json_error is not None or markdown_error is not None or (
        "core_instructions" not in json_text and "core_instructions" not in markdown
    )


def test_bearer_and_email_are_redacted_in_report_strings() -> None:
    report = _build(
        (_passing_score(),),
        config_summary={
            "contact": "Bearer super-secret-token-99 ada@example.com"
        },
    )
    json_text = report_to_json(report)
    markdown = report_to_markdown(report)
    assert "super-secret-token-99" not in json_text
    assert "ada@example.com" not in json_text
    assert "super-secret-token-99" not in markdown
    assert "ada@example.com" not in markdown
    assert "Bearer [REDACTED]" in json_text
    assert "[EMAIL]" in json_text
    assert "Bearer [REDACTED]" in markdown
    assert "[EMAIL]" in markdown


def test_compare_shrinking_case_set_is_regression() -> None:
    baseline = _report(
        case_ids=("uc-08-tenant-a-hours", "uc-01-tenant-a-start"),
    )
    current = _report(case_ids=("uc-08-tenant-a-hours",))
    comparison = compare_reports(baseline=baseline, current=current)
    assert comparison.passed is False
    assert "uc-01-tenant-a-start" in comparison.missing_cases


def test_compare_dataset_hash_mismatch_is_regression() -> None:
    comparison = compare_reports(
        baseline=_report(case_ids=("uc-08-tenant-a-hours",)),
        current=_report(dataset_hash="e" * 64, case_ids=("uc-08-tenant-a-hours",)),
    )
    assert comparison.passed is False
    assert comparison.gate_reason != "pass"


def test_compare_model_change_is_regression() -> None:
    comparison = compare_reports(
        baseline=_report(case_ids=("uc-08-tenant-a-hours",)),
        current=_report(model_name="other-llm", case_ids=("uc-08-tenant-a-hours",)),
    )
    assert comparison.passed is False
    assert comparison.gate_reason != "pass"
