"""Validate backend-neutral alerts, dashboards, and actionable runbooks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

ALERT_SCHEMA = "ia-mcp.observability.alert/v1"
DASHBOARD_SCHEMA = "ia-mcp.observability.dashboard/v1"
REQUIRED_ALERT_FIELDS = ("id", "owner", "severity", "window", "threshold", "dedupe", "runbook")
ALLOWED_SEVERITIES = frozenset({"critical", "high", "medium", "low"})
FORBIDDEN_DESTINATION_KEYS = frozenset(
    {
        "destination",
        "pagerduty",
        "datadog",
        "grafana",
        "webhook",
        "api_key",
        "credentials",
    }
)
HIGH_CARDINALITY_LABELS = frozenset(
    {
        "conversation_id",
        "run_id",
        "patient_id",
        "document_id",
        "message_id",
        "workflow_id",
        "job_id",
        "tool_execution_id",
    }
)
REQUIRED_RUNBOOK_SECTIONS = {
    "diagnosis": ("diagnosis", "diagnóstico", "diagnostico"),
    "mitigation": ("safe mitigation", "mitigación segura", "mitigacion segura"),
    "verification": ("verification", "verificación", "verificacion"),
    "escalation": ("escalation", "escalamiento"),
    "close": ("close", "cierre", "criterio de cierre"),
}
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+)$")
SECRET_PATTERN = re.compile(
    r"(?i)\b(bearer)\s+\S+|\b(api[_-]?key)\s*[=:]\s*\S+|"
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}|"
    r"\bDNI\s*:?\s*\d{7,8}\b|\+\d{1,3}(?:[\s-]?\d{2,4}){2,4}"
)
SLUG_CONDITIONAL_PATTERN = re.compile(
    r"(?i)(?:if\s+tenant_slug|tenant_slug\s*==|if\s+slug\s*==|slug\s*==\s*['\"])"
)
MUTATING_VIEW_PATTERN = re.compile(r"(?i)\b(?:post|patch|put|delete)\s+/admin/runs\b")
DEFAULT_TABLETOP = Path("observability/tabletop/synthetic-unknown-outcome.json")


@dataclass(frozen=True)
class Finding:
    """One validation violation with a reproducible location."""

    path: Path
    line: int
    message: str

    def __str__(self) -> str:
        return f"{path_display(self.path)}:{self.line}: {self.message}"


@dataclass(frozen=True)
class TabletopResult:
    """Sanitized reconstruction of a synthetic incident."""

    incident_id: str
    alert_id: str
    cause: str
    mutations: tuple[str, ...]
    workflow_state: str
    evidence_ids: tuple[str, ...]

    def render(self) -> str:
        lines = [
            f"incident_id={self.incident_id}",
            f"alert_id={self.alert_id}",
            f"cause={self.cause}",
            f"workflow_state={self.workflow_state}",
            "mutations:",
            *[f"  - {item}" for item in self.mutations],
            "evidence_ids:",
            *[f"  - {item}" for item in self.evidence_ids],
        ]
        return "\n".join(lines)


def path_display(path: Path) -> str:
    return str(path)


def load_json_object(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError(f"{path}: document must be a JSON object")
    return cast(dict[str, object], raw)


def json_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.json") if path.is_file())


def markdown_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.md") if path.is_file())


def markdown_sections(text: str) -> list[tuple[str, str, int]]:
    sections: list[tuple[str, str, int]] = []
    heading = ""
    heading_line = 1
    content: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = HEADING_PATTERN.match(line)
        if match:
            if heading:
                sections.append((heading, "\n".join(content).strip(), heading_line))
            heading = match.group(1).strip().lower()
            heading_line = line_number
            content = []
        elif heading:
            content.append(line)
    if heading:
        sections.append((heading, "\n".join(content).strip(), heading_line))
    return sections


def has_section(sections: Sequence[tuple[str, str, int]], aliases: Sequence[str]) -> bool:
    return any(heading in aliases and body for heading, body, _ in sections)


def validate_alert(
    path: Path,
    *,
    runbooks_dir: Path | None = None,
    repo_root: Path | None = None,
) -> list[Finding]:
    """Reject alerts that cannot be owned, thresholded, or actioned."""
    findings: list[Finding] = []
    try:
        document = load_json_object(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [Finding(path, 1, f"invalid alert document: {exc}")]

    for key in FORBIDDEN_DESTINATION_KEYS:
        if key in document:
            findings.append(Finding(path, 1, f"invented destination field '{key}'"))

    schema = document.get("schema")
    if schema != ALERT_SCHEMA:
        findings.append(Finding(path, 1, f"alert schema must be {ALERT_SCHEMA}"))

    for field in REQUIRED_ALERT_FIELDS:
        value = document.get(field)
        if value in (None, "", [], {}):
            findings.append(Finding(path, 1, f"missing required field '{field}'"))

    owner = document.get("owner")
    if isinstance(owner, str) and not owner.strip():
        findings.append(Finding(path, 1, "missing required field 'owner'"))

    severity = document.get("severity")
    if isinstance(severity, str) and severity not in ALLOWED_SEVERITIES:
        findings.append(Finding(path, 1, f"unsupported severity '{severity}'"))

    threshold = document.get("threshold")
    if isinstance(threshold, Mapping):
        for field in ("metric", "operator", "value"):
            if threshold.get(field) in (None, ""):
                findings.append(Finding(path, 1, f"missing threshold.{field}"))
    elif threshold not in (None, "", [], {}):
        findings.append(Finding(path, 1, "threshold must be an object"))

    dedupe = document.get("dedupe")
    if isinstance(dedupe, Mapping):
        if not dedupe.get("key"):
            findings.append(Finding(path, 1, "missing dedupe.key"))
        if not dedupe.get("window"):
            findings.append(Finding(path, 1, "missing dedupe.window"))
    elif dedupe not in (None, "", [], {}):
        findings.append(Finding(path, 1, "dedupe must be an object"))

    runbook = document.get("runbook")
    if (
        isinstance(runbook, str)
        and runbook.strip()
        and (runbooks_dir is not None or repo_root is not None)
        and not _runbook_exists(runbook, runbooks_dir, repo_root)
    ):
        findings.append(Finding(path, 1, f"runbook '{runbook}' does not exist"))
    return findings


def _runbook_exists(
    runbook_field: str,
    runbooks_dir: Path | None,
    repo_root: Path | None,
) -> bool:
    name = Path(runbook_field).name
    if runbooks_dir is not None and (runbooks_dir / name).is_file():
        return True
    if repo_root is not None and (repo_root / runbook_field).is_file():
        return True
    return runbooks_dir is None and repo_root is None


def validate_runbook(path: Path) -> list[Finding]:
    """Reject runbooks that lack a closeable verification step."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding(path, 1, f"unreadable runbook: {exc}")]

    findings: list[Finding] = []
    sections = markdown_sections(text)
    for name, aliases in REQUIRED_RUNBOOK_SECTIONS.items():
        if not has_section(sections, aliases):
            findings.append(Finding(path, 1, f"missing required section '{name}'"))

    if SECRET_PATTERN.search(text):
        findings.append(Finding(path, 1, "runbook contains a secret or PII pattern"))
    if SLUG_CONDITIONAL_PATTERN.search(text):
        findings.append(Finding(path, 1, "runbook branches on a tenant slug"))
    if MUTATING_VIEW_PATTERN.search(text):
        findings.append(
            Finding(path, 1, "runbook mutates production via the run investigation view")
        )
    return findings


def validate_dashboard(path: Path) -> list[Finding]:
    try:
        document = load_json_object(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [Finding(path, 1, f"invalid dashboard document: {exc}")]

    findings: list[Finding] = []
    for key in FORBIDDEN_DESTINATION_KEYS:
        if key in document:
            findings.append(Finding(path, 1, f"invented destination field '{key}'"))
    if document.get("schema") != DASHBOARD_SCHEMA:
        findings.append(Finding(path, 1, f"dashboard schema must be {DASHBOARD_SCHEMA}"))
    for field in ("id", "title", "panels"):
        if document.get(field) in (None, "", [], {}):
            findings.append(Finding(path, 1, f"missing required field '{field}'"))
    panels = document.get("panels")
    if isinstance(panels, list):
        for panel in panels:
            if not isinstance(panel, Mapping):
                findings.append(Finding(path, 1, "panel must be an object"))
                continue
            labels = panel.get("labels", [])
            if isinstance(labels, list):
                forbidden = HIGH_CARDINALITY_LABELS.intersection(str(item) for item in labels)
                if forbidden:
                    findings.append(
                        Finding(
                            path,
                            1,
                            "dashboard uses high-cardinality labels "
                            + ", ".join(sorted(forbidden)),
                        )
                    )
    return findings


def validate_tree(
    runbooks_dir: Path,
    *,
    alerts_dir: Path | None = None,
    dashboards_dir: Path | None = None,
    repo_root: Path | None = None,
    expected_alert_ids: Iterable[str] | None = None,
    expected_runbooks: Iterable[str] | None = None,
) -> list[Finding]:
    """Validate a runbook tree and the optional alert/dashboard catalogs."""
    findings: list[Finding] = []
    runbook_paths = markdown_files(runbooks_dir)
    if not runbook_paths:
        findings.append(Finding(runbooks_dir, 1, "no runbooks found"))
    for path in runbook_paths:
        findings.extend(validate_runbook(path))

    if expected_runbooks is not None:
        present = {path.name for path in runbook_paths}
        findings.extend(
            Finding(runbooks_dir, 1, f"missing required runbook '{name}'")
            for name in sorted(set(expected_runbooks) - present)
        )

    if alerts_dir is not None:
        alert_paths = json_files(alerts_dir)
        if not alert_paths:
            findings.append(Finding(alerts_dir, 1, "no alerts found"))
        alert_ids: set[str] = set()
        for path in alert_paths:
            findings.extend(
                validate_alert(path, runbooks_dir=runbooks_dir, repo_root=repo_root)
            )
            try:
                alert_id = load_json_object(path).get("id")
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(alert_id, str):
                alert_ids.add(alert_id)
        if expected_alert_ids is not None:
            findings.extend(
                Finding(alerts_dir, 1, f"missing required alert '{alert_id}'")
                for alert_id in sorted(set(expected_alert_ids) - alert_ids)
            )

    if dashboards_dir is not None:
        dashboard_paths = json_files(dashboards_dir)
        if not dashboard_paths:
            findings.append(Finding(dashboards_dir, 1, "no dashboards found"))
        for path in dashboard_paths:
            findings.extend(validate_dashboard(path))

    return sorted(findings, key=lambda finding: (str(finding.path), finding.line, finding.message))


def _walk_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        found: list[str] = []
        for item in value.values():
            found.extend(_walk_strings(item))
        return found
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        found = []
        for item in value:
            found.extend(_walk_strings(item))
        return found
    return []


def reconstruct_tabletop(incident: Mapping[str, object]) -> TabletopResult:
    """Rebuild cause and mutations from structured IDs, never free-text logs."""
    if "free_text_logs" in incident:
        raise ValueError("tabletop must not include free-text logs of PII or secrets")

    for text in _walk_strings(incident):
        if SECRET_PATTERN.search(text):
            raise ValueError("tabletop contains a secret or PII pattern")
        if "Juan Perez" in text:
            raise ValueError("tabletop contains a free-text personal name")

    run = incident.get("run")
    workflow = incident.get("workflow")
    tools = incident.get("tools")
    run_map = run if isinstance(run, Mapping) else {}
    workflow_map = workflow if isinstance(workflow, Mapping) else {}
    tool_rows = tools if isinstance(tools, list) else []

    error_code = str(run_map.get("error_code") or "unknown")
    skill = str(run_map.get("skill") or "unknown")
    workflow_state = str(workflow_map.get("state") or "unknown")
    workflow_type = str(workflow_map.get("type") or "unknown")

    mutations: list[str] = []
    for tool in tool_rows:
        if not isinstance(tool, Mapping):
            continue
        tool_name = str(tool.get("tool_name") or "unknown")
        tool_error = tool.get("error_code") or tool.get("status") or "unknown"
        mutations.append(f"{tool_name} outcome={tool_error}")

    if workflow_state:
        mutations.append(f"workflow {workflow_type} -> {workflow_state}")

    evidence_ids = [
        str(value)
        for key in ("id", "correlation_id", "workflow_id")
        for source in (run_map, workflow_map, incident)
        if (value := source.get(key)) is not None
    ]

    return TabletopResult(
        incident_id=str(incident.get("incident_id") or "unknown"),
        alert_id=str(incident.get("alert_id") or "unknown"),
        cause=f"{error_code} during {skill}",
        mutations=tuple(mutations),
        workflow_state=workflow_state,
        evidence_ids=tuple(evidence_ids),
    )


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate observability runbooks and alerts.")
    parser.add_argument("runbooks", type=Path, help="Directory of Markdown runbooks")
    parser.add_argument(
        "--alerts",
        type=Path,
        default=None,
        help="Directory of backend-neutral alert documents",
    )
    parser.add_argument(
        "--dashboards",
        type=Path,
        default=None,
        help="Directory of backend-neutral dashboard documents",
    )
    parser.add_argument(
        "--tabletop",
        type=Path,
        default=None,
        help="Structured synthetic incident for AC-P07-010",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = repository_root()
    runbooks_dir = args.runbooks if args.runbooks.is_absolute() else root / args.runbooks
    alerts_dir = args.alerts or (root / "observability" / "alerts")
    dashboards_dir = args.dashboards or (root / "observability" / "dashboards")
    tabletop_path = args.tabletop or (root / DEFAULT_TABLETOP)

    findings = validate_tree(
        runbooks_dir,
        alerts_dir=alerts_dir,
        dashboards_dir=dashboards_dir,
        repo_root=root,
        expected_alert_ids=(
            "isolation-violation",
            "unknown-mutation-outcome",
            "upstream-outage",
            "queue-backlog",
            "rollback-config-integration",
        ),
        expected_runbooks=(
            "isolation.md",
            "unknown-outcome.md",
            "upstream.md",
            "queue.md",
            "rollback.md",
        ),
    )
    for finding in findings:
        print(finding, file=sys.stderr)

    if tabletop_path.is_file():
        try:
            result = reconstruct_tabletop(load_json_object(tabletop_path))
        except ValueError as exc:
            print(f"{tabletop_path}:1: {exc}", file=sys.stderr)
            findings.append(Finding(tabletop_path, 1, str(exc)))
        else:
            print(result.render())

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
