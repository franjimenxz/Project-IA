"""Deterministic checks for requirement-to-acceptance traceability."""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REQUIREMENT_ID_PATTERN = re.compile(r"\b(?P<prefix>RF|RNF)-(?P<number>\d{3})\b")
REQUIREMENT_RANGE_PATTERN = re.compile(
    r"\b(?P<prefix>RF|RNF)-(?P<start>\d{3})\s*[–-]\s*"
    r"(?:(?P<end_prefix>RF|RNF)-)?(?P<end>\d{3})\b"
)
ACCEPTANCE_ID_PATTERN = re.compile(r"\bAC-P(?P<phase>\d{2})-(?P<number>\d{3})\b")
ACCEPTANCE_RANGE_PATTERN = re.compile(
    r"\bAC-P(?P<phase>\d{2})-(?P<start>\d{3})\s*[–-]\s*"
    r"(?:AC-P(?P<end_phase>\d{2})-)?(?P<end>\d{3})\b"
)
ACCEPTANCE_SCENARIO_PATTERN = re.compile(
    r"^\s*Scenario:\s+(AC-P\d{2}-\d{3})\b", re.IGNORECASE
)


@dataclass(frozen=True)
class Finding:
    """One traceability violation with a reproducible Markdown location."""

    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def table_rows(document: str) -> list[tuple[int, list[str]]]:
    """Return Markdown table rows with line numbers, excluding separators."""
    rows: list[tuple[int, list[str]]] = []
    lines = document.splitlines()
    line_index = 0
    while line_index + 1 < len(lines):
        header = markdown_table_cells(lines[line_index])
        separator = markdown_table_cells(lines[line_index + 1])
        if header is None or separator is None or not is_table_separator(separator):
            line_index += 1
            continue
        rows.append((line_index + 1, header))
        line_index += 2
        while line_index < len(lines):
            cells = markdown_table_cells(lines[line_index])
            if cells is None or is_table_separator(cells):
                break
            rows.append((line_index + 1, cells))
            line_index += 1
    return rows


def markdown_table_cells(line: str) -> list[str] | None:
    """Return potential cells from one Markdown table line."""
    if "|" not in line:
        return None
    return [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]


def is_table_separator(cells: list[str]) -> bool:
    """Return whether cells are a valid Markdown table separator row."""
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def table_cells(document: str) -> list[list[str]]:
    """Return Markdown table cells, excluding separators and narrative text."""
    return [cells for _, cells in table_rows(document)]


def parse_catalog_rows(catalog: str, *, priority: str, prefixes: set[str]) -> set[str]:
    """Return requirement IDs from catalog rows with the requested priority."""
    requirements: set[str] = set()
    for cells in table_cells(catalog):
        if not cells or (match := REQUIREMENT_ID_PATTERN.fullmatch(cells[0])) is None:
            continue
        if match.group("prefix") in prefixes and priority in cells:
            requirements.add(match.group())
    return requirements


def parse_matrix_requirement_cells(matrix: str) -> set[str]:
    """Return RF/RNF identifiers and ranges found exclusively in matrix table cells."""
    return {
        match.group()
        for cells in table_cells(matrix)
        for cell in cells
        for match in REQUIREMENT_ID_PATTERN.finditer(cell)
    }


def expand_identifier_ranges(identifiers: set[str], matrix: str) -> set[str]:
    """Expand RF/RNF ranges found in matrix cells alongside individual identifiers."""
    covered = set(identifiers)
    for cells in table_cells(matrix):
        for cell in cells:
            for match in REQUIREMENT_RANGE_PATTERN.finditer(cell):
                prefix = match.group("prefix")
                end_prefix = match.group("end_prefix")
                if end_prefix is not None and end_prefix != prefix:
                    continue
                start = int(match.group("start"))
                end = int(match.group("end"))
                covered.update(f"{prefix}-{number:03d}" for number in range(start, end + 1))
    return covered


def missing_must_requirements(catalog: str, matrix: str) -> set[str]:
    """Return required RF/RNF IDs that lack a table-backed matrix reference."""
    required = parse_catalog_rows(catalog, priority="must", prefixes={"RF", "RNF"})
    covered = expand_identifier_ranges(parse_matrix_requirement_cells(matrix), matrix)
    return required - covered


def defined_acceptance_ids(paths: Sequence[Path]) -> set[str]:
    """Return IDs defined by acceptance table rows or Gherkin Scenario headings."""
    identifiers: set[str] = set()
    for path in sorted(paths, key=str):
        document = path.read_text(encoding="utf-8")
        for _, cells in table_rows(document):
            if cells and ACCEPTANCE_ID_PATTERN.fullmatch(cells[0]):
                identifiers.add(cells[0])
        identifiers.update(
            match.group(1)
            for line in document.splitlines()
            if (match := ACCEPTANCE_SCENARIO_PATTERN.match(line))
        )
    return identifiers


def acceptance_ids_in_cell(cell: str) -> set[str]:
    """Return individual and range-expanded AC IDs from one matrix table cell."""
    identifiers = {match.group() for match in ACCEPTANCE_ID_PATTERN.finditer(cell)}
    for match in ACCEPTANCE_RANGE_PATTERN.finditer(cell):
        phase = match.group("phase")
        end_phase = match.group("end_phase")
        if end_phase is not None and end_phase != phase:
            continue
        start = int(match.group("start"))
        end = int(match.group("end"))
        identifiers.update(f"AC-P{phase}-{number:03d}" for number in range(start, end + 1))
    return identifiers


def acceptance_reference_findings(
    matrix_path: Path, acceptance_paths: Sequence[Path]
) -> list[Finding]:
    """Report matrix AC references not defined by phase acceptance criteria."""
    defined = defined_acceptance_ids(acceptance_paths)
    findings: list[Finding] = []
    for line_number, cells in table_rows(matrix_path.read_text(encoding="utf-8")):
        referenced = {identifier for cell in cells for identifier in acceptance_ids_in_cell(cell)}
        findings.extend(
            Finding(matrix_path, line_number, f"undefined acceptance criterion '{identifier}'")
            for identifier in sorted(referenced - defined)
        )
    return findings


def traceability_findings(
    catalog_path: Path, matrix_path: Path, acceptance_paths: Sequence[Path]
) -> list[Finding]:
    """Return every coverage and acceptance-reference violation in stable order."""
    missing = missing_must_requirements(
        catalog_path.read_text(encoding="utf-8"), matrix_path.read_text(encoding="utf-8")
    )
    coverage_findings = [
        Finding(matrix_path, 1, f"missing must requirement '{identifier}'")
        for identifier in sorted(missing)
    ]
    return coverage_findings + acceptance_reference_findings(matrix_path, acceptance_paths)


def main() -> int:
    """Validate the repository's global requirement traceability matrix."""
    repository_root = Path(__file__).resolve().parents[1]
    docs = repository_root / "docs"
    findings = traceability_findings(
        docs / "00-governance" / "requirements-catalog.md",
        docs / "00-governance" / "traceability-matrix.md",
        sorted(docs.glob("phases/**/acceptance-criteria.md")),
    )
    for finding in findings:
        print(finding, file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
