"""Fail the gate when Core gains tenant-name or slug branches."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ALLOWED_PREFIXES: tuple[str, ...] = (
    "tenants/",
    "tests/",
    "docs/",
    "scripts/",
    "evals/",
)
CORE_PREFIX = "src/ia_mcp/"
ADAPTER_MARKER = "/adapters/"
PathKind = Literal["allowed", "core", "other"]

_COMPARISON = re.compile(
    r"(?:if|elif|case)\s+(?P<left>[^\n:]+?)(?P<op>==|!=|in)\s*"
    r"(?P<right>['\"][^'\"]+['\"]|\{[^}]*['\"][^}]*\})",
    re.IGNORECASE,
)
_MATCH_CASE = re.compile(
    r"match\s+(?P<subject>[^\n:]+):\s*\n(?:[ \t]*#.*\n)*[ \t]*case\s+['\"]",
    re.IGNORECASE,
)
_SLUG_HINT = re.compile(
    r"\b(?:tenant_slug|tenant_name|institution(?:_name)?)\b|\.slug\b|(?<![\w])slug(?![\w])",
    re.IGNORECASE,
)
_TENANT_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+tenants(?:\.|/)",
    re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.code}: {self.message}"


def classify_path(path: str) -> PathKind:
    normalized = path.replace("\\", "/")
    if normalized.startswith(ALLOWED_PREFIXES):
        return "allowed"
    if normalized.startswith(CORE_PREFIX) and ADAPTER_MARKER in f"/{normalized}":
        return "allowed"
    if normalized.startswith((CORE_PREFIX, "alembic/")):
        return "core"
    return "other"


def find_slug_branches(source: str) -> tuple[str, ...]:
    matches: list[str] = []
    for match in _COMPARISON.finditer(source):
        left = match.group("left")
        if _SLUG_HINT.search(left) or _SLUG_HINT.search(match.group(0)):
            matches.append(" ".join(match.group(0).split()))
    for match in _MATCH_CASE.finditer(source):
        if _SLUG_HINT.search(match.group("subject")):
            matches.append(" ".join(match.group(0).split()))
    return tuple(matches)


def review_changeset(files: Mapping[str, str]) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for path, source in files.items():
        if classify_path(path) != "core":
            continue
        findings.append(
            Finding(
                path=path,
                code="core_change",
                message=f"Core file changed: {path}",
            )
        )
        findings.extend(_source_findings(path, source))
    return tuple(findings)


def scan_core_tree(root: Path) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    core_root = root / "src" / "ia_mcp"
    if not core_root.is_dir():
        return ()
    for path in sorted(core_root.rglob("*.py")):
        relative = str(path.relative_to(root)).replace("\\", "/")
        if classify_path(relative) != "core":
            continue
        findings.extend(_source_findings(relative, path.read_text(encoding="utf-8")))
    return tuple(findings)


def collect_changed_files(base: str, root: Path) -> dict[str, str]:
    names = set(_git(["diff", "--name-only", base], root))
    names.update(_git(["ls-files", "--others", "--exclude-standard"], root))
    files: dict[str, str] = {}
    for name in sorted(names):
        if not name or name.startswith(".venv/"):
            continue
        path = root / name
        if path.is_file():
            files[name] = (
                path.read_text(encoding="utf-8") if path.suffix == ".py" else ""
            )
            continue
        if name.endswith(".py"):
            files[name] = ""
    return files


def review_repository(base: str, root: Path) -> tuple[Finding, ...]:
    findings = list(review_changeset(collect_changed_files(base, root)))
    seen = {(item.path, item.code, item.message) for item in findings}
    for item in scan_core_tree(root):
        key = (item.path, item.code, item.message)
        if key not in seen:
            findings.append(item)
            seen.add(key)
    return tuple(findings)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject tenant-name or slug branches in Core."
    )
    parser.add_argument("--base", required=True, help="Registered baseline git hash")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root (defaults to the current directory)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.root.resolve()
    findings = review_repository(str(args.base), root)
    for finding in findings:
        print(finding)
    return 1 if findings else 0


def _source_findings(path: str, source: str) -> tuple[Finding, ...]:
    findings = [
        Finding(
            path=path,
            code="slug_branch",
            message=f"tenant slug/name branch: {branch}",
        )
        for branch in find_slug_branches(source)
    ]
    if _TENANT_IMPORT.search(source):
        findings.append(
            Finding(
                path=path,
                code="tenant_package_import",
                message="Core imports a tenant package",
            )
        )
    return tuple(findings)


def _git(arguments: Sequence[str], root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or "git diff failed"
        raise SystemExit(f"unable to diff against base: {message}")
    return tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())


if __name__ == "__main__":
    raise SystemExit(main())
