"""Deterministic quality checks for Markdown documentation."""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

ID_PATTERN = re.compile(r"\b(?:UC|RF|RNF|BR|CON|EXT)-\d{2,3}\b")
HEADING_ID_PATTERN = re.compile(
    r"^\s{0,3}#{1,6}\s+((?:UC|RF|RNF|BR|CON|EXT)-\d{2,3})\b"
)
LINK_PATTERN = re.compile(r"(?<!!)\[[^]]*\]\(([^)]+)\)")
TOKEN_PATTERN = re.compile(r"\{\{[^{}\n]+\}\}")
PLACEHOLDER_PATTERN = re.compile(r"\b(?:TODO|TBD|PLACEHOLDER)\b")
GATE_DEFINITION_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(G\d+)\b")
GATE_REFERENCE_PATTERN = re.compile(r"\b(G\d+)\b")
BRIEF_NAME_PATTERN = re.compile(r"^P\d{2}-T\d{2}-.+\.md$")
MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+)$")
COMMAND_PATTERN = re.compile(r"\b(?:pytest|python|ruff|mypy|npm|pnpm|make)\b", re.IGNORECASE)
SIGNATURE_PATTERN = re.compile(r"`[^`]*\([^`]*\)[^`]*`")
RED_GREEN_PATTERN = re.compile(r"\brojo\b.*\bverde\b", re.IGNORECASE | re.DOTALL)
DOCUMENTARY_EVIDENCE_PATTERN = re.compile(
    r"\b(?:review|sign-off|signoff|falla|fail|fuente|source|criterio|acceptance)\b",
    re.IGNORECASE,
)
IMPLEMENTATION_PATTERN = re.compile(
    r"\b(?:produce|consume)\b\s+\S+|"
    r"\b(?:implement[aá]|crear|creá)\b[^\n]*(?:`[^`]+`|"
    r"\b(?:schema|models?|validator|registry|service|workflow|contract|adapter|"
    r"catalog|catálogo|port|protocol|route|endpoint|cli)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    """One documentation violation with a reproducible location."""

    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True)
class DefinitionOccurrence:
    """One normative identifier definition and its Markdown source form."""

    path: Path
    line: int
    identifier: str
    source: str


def markdown_files(paths: Iterable[Path]) -> list[Path]:
    """Return each Markdown input file once, in a deterministic order."""
    files: dict[Path, Path] = {}
    for path in paths:
        if path.is_dir():
            candidates = path.rglob("*.md")
        elif path.suffix.lower() == ".md":
            candidates = (path,)
        else:
            candidates = ()
        for candidate in candidates:
            files[candidate.resolve()] = candidate
    return [files[key] for key in sorted(files, key=lambda item: str(item))]


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def definition_id_occurrences(path: Path) -> list[DefinitionOccurrence]:
    """Locate IDs only in normative table rows and declaration headings."""
    occurrences: list[DefinitionOccurrence] = []
    in_definition_table = False
    for line_number, line in enumerate(read_lines(path), start=1):
        heading_match = HEADING_ID_PATTERN.match(line)
        if heading_match:
            occurrences.append(
                DefinitionOccurrence(path, line_number, heading_match.group(1), "heading")
            )
            continue
        if path.name != "requirements-catalog.md" or "|" not in line:
            in_definition_table = False
            continue
        first_column = line.strip().lstrip("|").split("|", maxsplit=1)[0].strip(" `")
        if first_column.lower() == "id":
            in_definition_table = True
        elif in_definition_table and ID_PATTERN.fullmatch(first_column):
            occurrences.append(DefinitionOccurrence(path, line_number, first_column, "table"))
    return occurrences


def definition_ids(path: Path) -> list[str]:
    """Extract IDs only from Markdown definition rows and declaration headings."""
    return [occurrence.identifier for occurrence in definition_id_occurrences(path)]


def definitions_by_id(paths: Sequence[Path]) -> dict[str, list[DefinitionOccurrence]]:
    """Group all definition occurrences by identifier."""
    grouped: dict[str, list[DefinitionOccurrence]] = defaultdict(list)
    for path in markdown_files(paths):
        for occurrence in definition_id_occurrences(path):
            grouped[occurrence.identifier].append(occurrence)
    return grouped


def allowed_use_case_pair(
    occurrences: Sequence[DefinitionOccurrence],
) -> frozenset[DefinitionOccurrence]:
    """Return the one intentional UC registry/detail pair, when present."""
    registry = next(
        (
            occurrence
            for occurrence in occurrences
            if occurrence.path.name == "requirements-catalog.md" and occurrence.source == "table"
        ),
        None,
    )
    detail = next(
        (
            occurrence
            for occurrence in occurrences
            if occurrence.path.name == "use-cases.md" and occurrence.source == "heading"
        ),
        None,
    )
    if registry is None or detail is None:
        return frozenset()
    return frozenset((registry, detail))


def duplicate_occurrences(
    paths: Sequence[Path],
) -> dict[str, list[DefinitionOccurrence]]:
    """Return definitions beyond the one permitted catalog/detail UC pair."""
    duplicates: dict[str, list[DefinitionOccurrence]] = {}
    for identifier, occurrences in definitions_by_id(paths).items():
        allowed = allowed_use_case_pair(occurrences) if identifier.startswith("UC-") else frozenset()
        if allowed:
            extra = [occurrence for occurrence in occurrences if occurrence not in allowed]
            if extra:
                duplicates[identifier] = extra
        elif len(occurrences) > 1:
            duplicates[identifier] = occurrences[1:]
    return duplicates


def check_unique_ids(paths: Sequence[Path]) -> list[str]:
    """Return sorted IDs that are defined more than once across *paths*."""
    return sorted(duplicate_occurrences(paths))


def link_destination(raw_destination: str) -> str:
    destination = raw_destination.strip().strip("<>")
    return destination.split(maxsplit=1)[0] if destination else ""


def is_local_destination(destination: str) -> bool:
    if not destination or destination.startswith("#"):
        return False
    parsed = urlsplit(destination)
    return not parsed.scheme and not parsed.netloc


def check_local_links(paths: Sequence[Path]) -> list[Finding]:
    """Report local Markdown links whose target file does not exist."""
    findings: list[Finding] = []
    for path in markdown_files(paths):
        in_code_fence = False
        for line_number, line in enumerate(read_lines(path), start=1):
            if line.lstrip().startswith(("```", "~~~")):
                in_code_fence = not in_code_fence
                continue
            if in_code_fence:
                continue
            for match in LINK_PATTERN.finditer(line):
                destination = link_destination(match.group(1))
                if not is_local_destination(destination):
                    continue
                target = urlsplit(destination).path
                if not target:
                    continue
                target_path = Path(target)
                resolved = target_path if target_path.is_absolute() else path.parent / target_path
                if not resolved.exists():
                    findings.append(
                        Finding(path, line_number, f"broken local link '{destination}'")
                    )
    return sorted(findings, key=lambda finding: (str(finding.path), finding.line, finding.message))


def is_template(path: Path) -> bool:
    parts = path.resolve().parts
    return any(
        part == "docs" and index + 1 < len(parts) and parts[index + 1] == "templates"
        for index, part in enumerate(parts)
    )


def check_placeholders(paths: Sequence[Path]) -> list[Finding]:
    """Report unresolved template syntax and placeholder words outside templates."""
    findings: list[Finding] = []
    for path in markdown_files(paths):
        if is_template(path):
            continue
        for line_number, line in enumerate(read_lines(path), start=1):
            findings.extend(
                Finding(path, line_number, f"unresolved template token '{match.group()}'")
                for match in TOKEN_PATTERN.finditer(line)
            )
            findings.extend(
                Finding(
                    path,
                    line_number,
                    f"unresolved placeholder word '{match.group().upper()}'",
                )
                for match in PLACEHOLDER_PATTERN.finditer(line)
            )
    return findings


def is_brief(path: Path) -> bool:
    return path.name != "README.md" and (
        path.parent.name == "agent-briefs" or BRIEF_NAME_PATTERN.fullmatch(path.name) is not None
    )


def heading_texts(lines: Sequence[str]) -> list[str]:
    return [
        match.group(1).strip().lower()
        for line in lines
        if (match := MARKDOWN_HEADING_PATTERN.match(line))
    ]


def markdown_sections(lines: Sequence[str]) -> list[tuple[str, str]]:
    """Return normalized headings with the body that belongs to each one."""
    sections: list[tuple[str, str]] = []
    heading = ""
    content: list[str] = []
    for line in lines:
        match = MARKDOWN_HEADING_PATTERN.match(line)
        if match:
            if heading:
                sections.append((heading, "\n".join(content).strip()))
            heading = match.group(1).strip().lower()
            content = []
        elif heading:
            content.append(line)
    if heading:
        sections.append((heading, "\n".join(content).strip()))
    return sections


def has_executable_contract(text: str) -> bool:
    return SIGNATURE_PATTERN.search(text) is not None or IMPLEMENTATION_PATTERN.search(text) is not None or (
        "cli" in text.lower() and COMMAND_PATTERN.search(text) is not None
    )


def has_implementation_contract(lines: Sequence[str]) -> bool:
    """Require an explicit interface/TDD contract, not just matching vocabulary."""
    sections = markdown_sections(lines)
    named_sections = [
        (heading, content)
        for heading, content in sections
        if "interfaz" in heading or "interface" in heading or "tdd" in heading
    ]
    if named_sections:
        return any(
            has_executable_contract(content)
            or ("tdd" in heading and has_executable_evidence(content))
            for heading, content in named_sections
        )
    return has_executable_contract("\n".join(content for _, content in sections))


def has_executable_evidence(text: str) -> bool:
    return COMMAND_PATTERN.search(text) is not None or re.search(
        r"\b(?:ejecutar|ejecutá)\b[^\n]*`[^`]+`",
        text,
        re.IGNORECASE,
    ) is not None or (
        RED_GREEN_PATTERN.search(text) is not None
        and DOCUMENTARY_EVIDENCE_PATTERN.search(text) is not None
    )


def has_verification_evidence(lines: Sequence[str]) -> bool:
    """Require executable evidence under a relevant heading or inline sequence."""
    sections = markdown_sections(lines)
    named_sections = [
        content
        for heading, content in sections
        if "verificaci" in heading or "evidencia" in heading
    ]
    if named_sections:
        return any(has_executable_evidence(content) for content in named_sections)
    return has_executable_evidence("\n".join(content for _, content in sections))


def check_brief_sections(paths: Sequence[Path]) -> list[Finding]:
    """Report briefs missing the required execution-contract sections."""
    findings: list[Finding] = []
    for path in markdown_files(paths):
        if not is_brief(path):
            continue
        lines = read_lines(path)
        headings = heading_texts(lines)
        required_sections = (
            ("Lectura obligatoria", any("lectura obligatoria" in item for item in headings)),
            ("Archivos", any("archivo" in item for item in headings)),
            (
                "Interfaces/TDD",
                has_implementation_contract(lines),
            ),
            (
                "Verificación",
                has_verification_evidence(lines),
            ),
            ("Commit", any(re.search(r"\bcommit\b", line, re.IGNORECASE) for line in lines)),
        )
        for section, present in required_sections:
            if not present:
                findings.append(
                    Finding(path, 1, f"missing required brief section '{section}'")
                )
    return findings


def check_gates(paths: Sequence[Path]) -> list[Finding]:
    """Report undefined gate references and circular phase entry/exit gates."""
    files = markdown_files(paths)
    defined_gates = {
        match.group(1)
        for path in files
        for line in read_lines(path)
        if (match := GATE_DEFINITION_PATTERN.match(line))
    }
    findings: list[Finding] = []
    for path in files:
        entry_gates: set[str] = set()
        exit_gates: set[str] = set()
        for line_number, line in enumerate(read_lines(path), start=1):
            if GATE_DEFINITION_PATTERN.match(line):
                continue
            lower_line = line.lower()
            references = GATE_REFERENCE_PATTERN.findall(line)
            if "gate" not in lower_line:
                continue
            for gate in references:
                if gate not in defined_gates:
                    findings.append(
                        Finding(path, line_number, f"references undefined gate {gate}")
                    )
            if "gate de entrada" in lower_line or "gate preparatorio" in lower_line:
                entry_gates.update(references)
            if "gate de salida" in lower_line:
                exit_gates.update(references)
        for gate in sorted(entry_gates & exit_gates):
            exit_line = next(
                line_number
                for line_number, line in enumerate(read_lines(path), start=1)
                if "gate de salida" in line.lower() and gate in GATE_REFERENCE_PATTERN.findall(line)
            )
            findings.append(
                Finding(
                    path,
                    exit_line,
                    f"gate de salida {gate} repeats gate de entrada {gate}",
                )
            )
    return sorted(findings, key=lambda finding: (str(finding.path), finding.line, finding.message))


def duplicate_id_findings(paths: Sequence[Path]) -> list[Finding]:
    """Locate every repeated definition after the first declaration."""
    return [
        Finding(occurrence.path, occurrence.line, f"duplicate definition ID {identifier}")
        for identifier, occurrences in duplicate_occurrences(paths).items()
        for occurrence in occurrences
    ]


def selected_findings(paths: Sequence[Path], checks: Sequence[str]) -> list[Finding]:
    """Run requested checks and present their output in stable path/line order."""
    findings: list[Finding] = []
    if "ids" in checks:
        findings.extend(duplicate_id_findings(paths))
    if "links" in checks:
        findings.extend(check_local_links(paths))
    if "placeholders" in checks:
        findings.extend(check_placeholders(paths))
    if "briefs" in checks:
        findings.extend(check_brief_sections(paths))
    if "gates" in checks:
        findings.extend(check_gates(paths))
    return sorted(findings, key=lambda finding: (str(finding.path), finding.line, finding.message))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate documentation quality gates.")
    checks = parser.add_mutually_exclusive_group(required=True)
    checks.add_argument("--ids", action="store_true", help="check duplicate definition IDs")
    checks.add_argument("--links", action="store_true", help="check local Markdown links")
    checks.add_argument("--placeholders", action="store_true", help="check unresolved placeholders")
    checks.add_argument("--briefs", action="store_true", help="check required brief sections")
    checks.add_argument("--gates", action="store_true", help="check gate references and circularity")
    checks.add_argument("--all", action="store_true", help="run every documentation check")
    parser.add_argument("paths", nargs="+", type=Path, help="Markdown files or directories")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks = ["ids", "links", "placeholders", "briefs", "gates"] if args.all else [
        name for name in ("ids", "links", "placeholders", "briefs", "gates") if getattr(args, name)
    ]
    findings = selected_findings(args.paths, checks)
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
