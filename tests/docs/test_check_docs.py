"""Black-box checks for the deterministic documentation quality gate."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_docs import (
    check_brief_sections,
    check_gates,
    check_local_links,
    check_placeholders,
    check_unique_ids,
)


def messages(findings: list[object]) -> list[str]:
    return [str(finding) for finding in findings]


def test_duplicate_definition_id_is_reported_but_narrative_references_are_valid(
    tmp_path: Path,
) -> None:
    """Removing duplicate detection from definition rows must fail this test."""
    catalog = tmp_path / "requirements-catalog.md"
    catalog.write_text(
        "| ID | Requirement |\n"
        "| --- | --- |\n"
        "| RF-001 | First definition |\n"
        "| RF-001 | Duplicate definition |\n"
        "RF-001 is referenced in this explanatory paragraph.\n",
        encoding="utf-8",
    )

    assert check_unique_ids([catalog]) == ["RF-001"]


def test_duplicate_case_heading_is_reported(tmp_path: Path) -> None:
    """Treating use-case headings as prose would miss a duplicate definition."""
    cases = tmp_path / "cases.md"
    cases.write_text("## UC-01 — First\n\n## UC-01 — Duplicate\n", encoding="utf-8")

    assert check_unique_ids([cases]) == ["UC-01"]


def test_registry_row_and_detail_heading_form_one_logical_use_case_definition(
    tmp_path: Path,
) -> None:
    """The intentional catalog/detail pair must not be reported as a duplicate UC."""
    catalog = tmp_path / "requirements-catalog.md"
    catalog.write_text(
        "| ID | Use case |\n| --- | --- |\n| UC-01 | Start conversation |\n",
        encoding="utf-8",
    )
    cases = tmp_path / "use-cases.md"
    cases.write_text("## UC-01 — Start conversation\n", encoding="utf-8")

    assert check_unique_ids([catalog, cases]) == []


def test_extra_registry_row_is_still_a_duplicate_beside_the_valid_use_case_pair(
    tmp_path: Path,
) -> None:
    """Allowing the catalog/detail pair must not permit an additional UC registry row."""
    catalog = tmp_path / "requirements-catalog.md"
    catalog.write_text(
        "| ID | Use case |\n"
        "| --- | --- |\n"
        "| UC-01 | Start conversation |\n"
        "| UC-01 | Duplicate registry entry |\n",
        encoding="utf-8",
    )
    cases = tmp_path / "use-cases.md"
    cases.write_text("## UC-01 — Start conversation\n", encoding="utf-8")

    assert check_unique_ids([catalog, cases]) == ["UC-01"]


def test_identifier_references_in_a_non_catalog_table_are_not_definitions(
    tmp_path: Path,
) -> None:
    """Treating every table's first column as normative would reject traceability rows."""
    matrix = tmp_path / "matrix.md"
    matrix.write_text(
        "| Requisito | Evidence |\n"
        "| --- | --- |\n"
        "| RF-001 | First reference |\n"
        "| RF-001 | Second reference |\n",
        encoding="utf-8",
    )

    assert check_unique_ids([matrix]) == []


def test_identifier_references_in_an_id_header_non_catalog_table_are_not_definitions(
    tmp_path: Path,
) -> None:
    """An ID column alone must not turn a matrix into a normative requirements catalog."""
    matrix = tmp_path / "traceability-matrix.md"
    matrix.write_text(
        "| ID | Evidence |\n"
        "| --- | --- |\n"
        "| RF-001 | First reference |\n"
        "| RF-001 | Second reference |\n",
        encoding="utf-8",
    )

    assert check_unique_ids([matrix]) == []


def test_broken_local_markdown_link_includes_source_and_line(tmp_path: Path) -> None:
    """Skipping relative Markdown destinations would hide a broken document link."""
    index = tmp_path / "index.md"
    index.write_text("[Missing guide](guide.md#setup)\n", encoding="utf-8")

    result = messages(check_local_links([index]))

    assert result == [f"{index}:1: broken local link 'guide.md#setup'"]


def test_existing_local_markdown_link_and_external_link_are_valid(tmp_path: Path) -> None:
    """Resolving valid local or external destinations as missing would be a false positive."""
    index = tmp_path / "index.md"
    guide = tmp_path / "guide.md"
    guide.write_text("# Setup\n", encoding="utf-8")
    index.write_text(
        "[Guide](guide.md#setup)\n[External](https://example.com/guide)\n",
        encoding="utf-8",
    )

    assert check_local_links([index]) == []


def test_code_fences_are_not_parsed_as_markdown_links(tmp_path: Path) -> None:
    """Parsing Python generic syntax as Markdown would create a false broken-link report."""
    source = tmp_path / "example.md"
    source.write_text("```python\nclass Result[T](BaseModel): ...\n```\n", encoding="utf-8")

    assert check_local_links([source]) == []


def test_template_tokens_and_placeholder_words_are_ignored_only_under_docs_templates(
    tmp_path: Path,
) -> None:
    """Only docs/templates may contain unresolved template values."""
    template = tmp_path / "docs" / "templates" / "brief.md"
    template.parent.mkdir(parents=True)
    template.write_text("{{name}} TODO\n", encoding="utf-8")
    draft = tmp_path / "docs" / "brief.md"
    draft.write_text("{{name}} TODO\n", encoding="utf-8")
    nested_template = tmp_path / "docs" / "phases" / "phase-01" / "templates" / "draft.md"
    nested_template.parent.mkdir(parents=True)
    nested_template.write_text("{{name}} TODO\n", encoding="utf-8")

    result = messages(check_placeholders([template, draft, nested_template]))

    assert result == [
        f"{draft}:1: unresolved template token '{{{{name}}}}'",
        f"{draft}:1: unresolved placeholder word 'TODO'",
        f"{nested_template}:1: unresolved template token '{{{{name}}}}'",
        f"{nested_template}:1: unresolved placeholder word 'TODO'",
    ]


def test_ordinary_spanish_words_are_not_placeholder_markers(tmp_path: Path) -> None:
    """Case-insensitive TODO matching would incorrectly flag ordinary documentation prose."""
    document = tmp_path / "guide.md"
    document.write_text("Todo requisito debe ser verificable.\n", encoding="utf-8")

    assert check_placeholders([document]) == []


def test_brief_missing_required_sections_is_reported(tmp_path: Path) -> None:
    """Dropping the interface/TDD requirement would allow an incomplete brief."""
    brief = tmp_path / "P01-T99-incomplete.md"
    brief.write_text(
        "# P01-T99 — Incomplete\n"
        "## Lectura obligatoria\ntext\n"
        "## Archivos permitidos\ntext\n"
        "## Verificación\npytest\n"
        "Commit: `test: incomplete`\n",
        encoding="utf-8",
    )

    result = messages(check_brief_sections([brief]))

    assert result == [f"{brief}:1: missing required brief section 'Interfaces/TDD'"]


def test_complete_brief_with_combined_interface_tdd_section_is_valid(tmp_path: Path) -> None:
    """Rejecting a combined Interfaces y TDD section would reject a complete brief."""
    brief = tmp_path / "P01-T99-complete.md"
    brief.write_text(
        "# P01-T99 — Complete\n"
        "## Lectura obligatoria\n`docs/README.md`\n"
        "## Archivos exactos\n`scripts/check_docs.py`\n"
        "## Interfaces y TDD\nProduce `validate(Path) -> Report`.\n"
        "## Verificación\n`pytest tests/docs -v`\n"
        "Commit: `test: complete`\n",
        encoding="utf-8",
    )

    assert check_brief_sections([brief]) == []


def test_brief_with_empty_interface_and_verification_headings_is_rejected(tmp_path: Path) -> None:
    """Empty semantic headings must not satisfy executable contract requirements."""
    brief = tmp_path / "P01-T99-empty-sections.md"
    brief.write_text(
        "# P01-T99 — Empty sections\n"
        "## Lectura obligatoria\n`docs/README.md`\n"
        "## Archivos permitidos\n`scripts/check_docs.py`\n"
        "## Interfaces y TDD\n"
        "## Verificación\n"
        "Commit: `test: empty sections`.\n",
        encoding="utf-8",
    )

    result = messages(check_brief_sections([brief]))

    assert result == [
        f"{brief}:1: missing required brief section 'Interfaces/TDD'",
        f"{brief}:1: missing required brief section 'Verificación'",
    ]


def test_brief_accepts_inline_red_green_verification_after_combined_file_interface_scope(
    tmp_path: Path,
) -> None:
    """Requiring a literal Verificación heading would reject an executable brief contract."""
    brief = tmp_path / "P01-T99-inline-sequence.md"
    brief.write_text(
        "# P01-T99 — Inline sequence\n"
        "## Lectura obligatoria\ntext\n"
        "## Archivos exactos e interfaces\n"
        "Crear `validator.py`; produce `validate(Path) -> Report`.\n"
        "Rojo: el caso inválido falla. Verde: Ejecutá `pytest tests/docs -v`.\n"
        "Evidence: exit code 0. Commit: `test: inline sequence`.\n",
        encoding="utf-8",
    )

    assert check_brief_sections([brief]) == []


def test_brief_accepts_cli_as_an_explicit_interface_without_an_interface_heading(
    tmp_path: Path,
) -> None:
    """A CLI contract is an interface even when its brief does not name a section literally."""
    brief = tmp_path / "P01-T99-cli.md"
    brief.write_text(
        "# P01-T99 — CLI\n"
        "## Lectura obligatoria\ntext\n"
        "## Archivos permitidos\n`scripts/validate.py`\n"
        "Tests docs necesarios para CLI.\n"
        "## Verificación\n`python scripts/validate.py --all docs`\n"
        "## Handoff\nCommit `test: validate docs`.\n",
        encoding="utf-8",
    )

    assert check_brief_sections([brief]) == []


def test_brief_accepts_a_typed_signature_as_an_interface_contract(tmp_path: Path) -> None:
    """A documented callable signature is an interface contract without implementation prose."""
    brief = tmp_path / "P01-T99-signature.md"
    brief.write_text(
        "# P01-T99 — Signature\n"
        "## Lectura obligatoria\n`docs/README.md`\n"
        "## Archivos permitidos\n`scripts/validator.py`\n"
        "## Interface\n`validate(catalog: str) -> set[str]`.\n"
        "## Verificación\n`pytest tests/docs -v`\n"
        "Commit: `test: typed signature`.\n",
        encoding="utf-8",
    )

    assert check_brief_sections([brief]) == []


def test_brief_accepts_a_tdd_red_green_sequence_as_its_contract(tmp_path: Path) -> None:
    """A populated TDD section with a real command is a valid executable contract."""
    brief = tmp_path / "P01-T99-tdd.md"
    brief.write_text(
        "# P01-T99 — TDD\n"
        "## Lectura obligatoria\n`docs/README.md`\n"
        "## Archivos permitidos\n`tests/docs/test_validator.py`\n"
        "## TDD y evidencia\n"
        "Rojo: el caso aislado falla. Verde: `pytest tests/docs/test_validator.py -v`.\n"
        "Commit: `test: tdd contract`.\n",
        encoding="utf-8",
    )

    assert check_brief_sections([brief]) == []


def test_brief_accepts_documentary_red_green_evidence_without_a_shell_command(
    tmp_path: Path,
) -> None:
    """A review-backed red/green evidence sequence is valid for a documentation-only brief."""
    brief = tmp_path / "P01-T99-documentary.md"
    brief.write_text(
        "# P01-T99 — Documentary\n"
        "## Lectura obligatoria\n`docs/README.md`\n"
        "## Archivos e interfaces\n"
        "Crear `mapping.md`; produce a cited capability decision.\n"
        "## Verificación y evidencia\n"
        "Rojo documental: mapping sin fuente falla review. Verde: cada decision tiene sign-off.\n"
        "Commit: `docs: validate mapping`.\n",
        encoding="utf-8",
    )

    assert check_brief_sections([brief]) == []


def test_brief_without_executable_verification_still_fails(tmp_path: Path) -> None:
    """Semantic matching must not permit a brief that lacks verifiability evidence."""
    brief = tmp_path / "P01-T99-no-verification.md"
    brief.write_text(
        "# P01-T99 — No verification\n"
        "## Lectura obligatoria\ntext\n"
        "## Archivos e interfaces\n`validator.py`\n"
        "Implementá `validate(Path) -> Report`.\n"
        "Commit: `test: missing verification`.\n",
        encoding="utf-8",
    )

    result = messages(check_brief_sections([brief]))

    assert result == [f"{brief}:1: missing required brief section 'Verificación'"]


def test_agent_brief_directory_readme_is_not_itself_a_task_brief(tmp_path: Path) -> None:
    """Classifying an agent-briefs README as a brief would create meaningless findings."""
    directory = tmp_path / "agent-briefs"
    directory.mkdir()
    readme = directory / "README.md"
    readme.write_text("# Brief index\n", encoding="utf-8")

    assert check_brief_sections([readme]) == []


def test_gate_reference_must_exist_and_entry_and_exit_cannot_be_circular(
    tmp_path: Path,
) -> None:
    """Removing gate definition or circularity checks would let an invalid phase pass."""
    roadmap = tmp_path / "roadmap.md"
    roadmap.write_text("### G0 — Ready\n", encoding="utf-8")
    phase = tmp_path / "phase.md"
    phase.write_text(
        "**Gate de entrada:** G0\n"
        "**Gate de salida:** G0\n"
        "**Gate auxiliar:** G9\n",
        encoding="utf-8",
    )

    result = messages(check_gates([roadmap, phase]))

    assert result == [
        f"{phase}:2: gate de salida G0 repeats gate de entrada G0",
        f"{phase}:3: references undefined gate G9",
    ]


def test_cli_all_returns_zero_for_clean_document_tree(tmp_path: Path) -> None:
    """A regression in --all orchestration must make the public gate command fail."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.md").write_text("[Guide](guide.md)\n", encoding="utf-8")
    (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/check_docs.py", "--all", str(docs)],
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[2],
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_quality_extra_is_installable_with_the_locked_documentation_tools(
    tmp_path: Path,
) -> None:
    """Removing the project quality extra must break the CI dependency install."""
    report = tmp_path / "install-report.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--report",
            str(report),
            ".[quality]",
        ],
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[2],
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    project = next(
        item["metadata"]
        for item in json.loads(report.read_text(encoding="utf-8"))["install"]
        if item["metadata"]["name"] == "ia-mcp"
    )
    assert set(project["requires_dist"]) == {
        "fastapi==0.141.1",
        'pytest==9.1.1; extra == "quality"',
        'ruff==0.16.5; extra == "quality"',
        'httpx==0.28.1; extra == "quality"',
        'mypy==2.3.1; extra == "quality"',
    }


def test_console_pytest_collects_documentation_tests_from_the_project_root() -> None:
    """Dropping the project import path must break the CI pytest command."""
    result = subprocess.run(
        [
            str(Path(sys.executable).with_name("pytest")),
            "tests/docs/test_traceability.py",
            "--collect-only",
            "-q",
        ],
        capture_output=True,
        check=False,
        cwd=Path(__file__).parents[2],
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
