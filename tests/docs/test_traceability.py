"""Tests for the deterministic requirements traceability checker."""

from __future__ import annotations

from pathlib import Path

from scripts.check_traceability import (
    acceptance_reference_findings,
    missing_must_requirements,
    traceability_findings,
)


def test_missing_must_requirement_is_reported() -> None:
    """Removing coverage detection must expose the uncovered must requirement."""
    catalog = (
        "| ID | Requirement | Priority |\n"
        "| --- | --- | --- |\n"
        "| RF-001 | Required capability | must |\n"
        "| RF-002 | Optional capability | should |\n"
    )
    matrix = (
        "| Requirements | Evidence |\n"
        "| --- | --- |\n"
        "| RF-002 | Covered elsewhere |\n"
    )

    assert missing_must_requirements(catalog, matrix) == {"RF-001"}


def test_individual_requirement_id_in_a_matrix_table_is_covered() -> None:
    """Changing individual-ID parsing must expose an otherwise covered requirement."""
    catalog = (
        "| ID | Requirement | Priority |\n"
        "| --- | --- | --- |\n"
        "| RF-001 | Required capability | must |\n"
    )
    matrix = (
        "| Requirements | Evidence |\n"
        "| --- | --- |\n"
        "| RF-001 | Covered here |\n"
    )

    assert missing_must_requirements(catalog, matrix) == set()


def test_full_and_shorthand_requirement_ranges_in_matrix_tables_are_covered() -> None:
    """Removing range expansion must expose every must requirement in those ranges."""
    catalog = (
        "| ID | Requirement | Priority |\n"
        "| --- | --- | --- |\n"
        "| RF-001 | First required capability | must |\n"
        "| RF-002 | Second required capability | must |\n"
        "| RF-003 | Third required capability | must |\n"
        "| RNF-001 | First quality requirement | must |\n"
        "| RNF-002 | Second quality requirement | must |\n"
    )
    matrix = (
        "| Requirements | Evidence |\n"
        "| --- | --- |\n"
        "| RF-001–003, RNF-001–RNF-002 | Covered ranges |\n"
    )

    assert missing_must_requirements(catalog, matrix) == set()


def test_only_must_rows_in_catalog_tables_require_coverage() -> None:
    """Treating non-must priorities as required would produce a false missing ID."""
    catalog = (
        "| ID | Requirement | Priority |\n"
        "| --- | --- | --- |\n"
        "| RF-001 | Required capability | must |\n"
        "| RF-002 | Deferred capability | should |\n"
        "| RNF-001 | Optional quality target | could |\n"
    )
    matrix = (
        "| Requirements | Evidence |\n"
        "| --- | --- |\n"
        "| RF-001 | Covered here |\n"
    )

    assert missing_must_requirements(catalog, matrix) == set()


def test_narrative_requirement_references_do_not_create_coverage() -> None:
    """Parsing prose as matrix coverage would hide the missing must requirement."""
    catalog = (
        "| ID | Requirement | Priority |\n"
        "| --- | --- | --- |\n"
        "| RF-001 | Required capability | must |\n"
        "Narrative says RF-002 is must, but it is not a catalog row.\n"
    )
    matrix = (
        "RF-001 appears in prose but not as a matrix table cell.\n"
        "| Requirements | Evidence |\n"
        "| --- | --- |\n"
        "| RF-002 | Unrelated table-backed reference |\n"
    )

    assert missing_must_requirements(catalog, matrix) == {"RF-001"}


def test_pipe_delimited_narrative_is_not_a_matrix_table() -> None:
    """Accepting arbitrary pipe text as a table would hide missing coverage."""
    catalog = (
        "| ID | Requirement | Priority |\n"
        "| --- | --- | --- |\n"
        "| RF-001 | Required capability | must |\n"
    )
    matrix = "Narrative reference: RF-001 | it is not a Markdown table.\n"

    assert missing_must_requirements(catalog, matrix) == {"RF-001"}


def test_full_and_shorthand_acceptance_ranges_resolve_to_defined_criteria(
    tmp_path: Path,
) -> None:
    """Removing AC range validation must leave valid table references unresolved."""
    matrix = tmp_path / "traceability-matrix.md"
    matrix.write_text(
        "| Criteria |\n"
        "| --- |\n"
        "| AC-P04-050–AC-P04-051, AC-P04-052–053 |\n",
        encoding="utf-8",
    )
    acceptance = tmp_path / "acceptance-criteria.md"
    acceptance.write_text(
        "| ID | Criterion |\n"
        "| --- | --- |\n"
        "| AC-P04-050 | First |\n"
        "| AC-P04-051 | Second |\n"
        "| AC-P04-052 | Third |\n"
        "| AC-P04-053 | Fourth |\n",
        encoding="utf-8",
    )

    assert acceptance_reference_findings(matrix, [acceptance]) == []


def test_undefined_acceptance_ids_and_range_endpoints_include_matrix_line(
    tmp_path: Path,
) -> None:
    """Ignoring an undefined AC reference would hide broken traceability evidence."""
    matrix = tmp_path / "traceability-matrix.md"
    matrix.write_text(
        "| Criteria |\n"
        "| --- |\n"
        "| AC-P04-050–052, AC-P04-099 |\n",
        encoding="utf-8",
    )
    acceptance = tmp_path / "acceptance-criteria.md"
    acceptance.write_text(
        "| ID | Criterion |\n"
        "| --- | --- |\n"
        "| AC-P04-050 | Defined only criterion |\n",
        encoding="utf-8",
    )

    assert [str(finding) for finding in acceptance_reference_findings(matrix, [acceptance])] == [
        f"{matrix}:3: undefined acceptance criterion 'AC-P04-051'",
        f"{matrix}:3: undefined acceptance criterion 'AC-P04-052'",
        f"{matrix}:3: undefined acceptance criterion 'AC-P04-099'",
    ]


def test_traceability_findings_reports_missing_coverage_and_acceptance_references(
    tmp_path: Path,
) -> None:
    """Removing the CLI check aggregation would suppress either failing condition."""
    catalog = tmp_path / "requirements-catalog.md"
    catalog.write_text(
        "| ID | Requirement | Priority |\n"
        "| --- | --- | --- |\n"
        "| RF-001 | Required capability | must |\n",
        encoding="utf-8",
    )
    matrix = tmp_path / "traceability-matrix.md"
    matrix.write_text(
        "| Requirements | Criteria |\n"
        "| --- | --- |\n"
        "| RF-002 | AC-P04-999 |\n",
        encoding="utf-8",
    )
    acceptance = tmp_path / "acceptance-criteria.md"
    acceptance.write_text("| ID | Criterion |\n| --- | --- |\n", encoding="utf-8")

    assert [str(finding) for finding in traceability_findings(catalog, matrix, [acceptance])] == [
        f"{matrix}:1: missing must requirement 'RF-001'",
        f"{matrix}:3: undefined acceptance criterion 'AC-P04-999'",
    ]
