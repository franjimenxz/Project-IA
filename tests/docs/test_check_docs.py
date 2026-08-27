"""Black-box checks for the deterministic documentation quality gate."""

from __future__ import annotations

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
    catalog = tmp_path / "catalog.md"
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


def test_template_tokens_and_placeholder_words_are_ignored_only_under_templates(
    tmp_path: Path,
) -> None:
    """Allowing placeholders outside docs/templates would leave unfinished docs unchecked."""
    template = tmp_path / "templates" / "brief.md"
    template.parent.mkdir()
    template.write_text("{{name}} TODO\n", encoding="utf-8")
    draft = tmp_path / "brief.md"
    draft.write_text("{{name}} TODO\n", encoding="utf-8")

    result = messages(check_placeholders([template, draft]))

    assert result == [
        f"{draft}:1: unresolved template token '{{{{name}}}}'",
        f"{draft}:1: unresolved placeholder word 'TODO'",
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
        "## Lectura obligatoria\ntext\n"
        "## Archivos exactos\ntext\n"
        "## Interfaces y TDD\ntext\n"
        "## Verificación\npytest\n"
        "Commit: `test: complete`\n",
        encoding="utf-8",
    )

    assert check_brief_sections([brief]) == []


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
