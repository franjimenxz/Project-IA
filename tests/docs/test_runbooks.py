"""Black-box checks for alert and runbook operability contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.verify_runbooks import (
    reconstruct_tabletop,
    validate_alert,
    validate_runbook,
    validate_tree,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS_DIR = REPO_ROOT / "docs" / "runbooks"
ALERTS_DIR = REPO_ROOT / "observability" / "alerts"
DASHBOARDS_DIR = REPO_ROOT / "observability" / "dashboards"
TABLETOP_PATH = REPO_ROOT / "observability" / "tabletop" / "synthetic-unknown-outcome.json"

REQUIRED_ALERT_IDS = (
    "isolation-violation",
    "unknown-mutation-outcome",
    "upstream-outage",
    "queue-backlog",
    "rollback-config-integration",
)
REQUIRED_RUNBOOKS = (
    "isolation.md",
    "unknown-outcome.md",
    "upstream.md",
    "queue.md",
    "rollback.md",
)
FORBIDDEN_DESTINATION_KEYS = (
    "destination",
    "pagerduty",
    "datadog",
    "grafana",
    "webhook",
    "api_key",
    "credentials",
)
PII_MARKERS = (
    "Bearer secret-token",
    "patient@example.com",
    "30111222",
    "+54 11 5555 0000",
)


def _write_alert(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _complete_alert(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "ia-mcp.observability.alert/v1",
        "id": "isolation-violation",
        "title": "Tenant isolation violation",
        "owner": "platform-security",
        "severity": "critical",
        "window": "5m",
        "threshold": {"metric": "isolation_violation_count", "operator": ">=", "value": 1},
        "dedupe": {"key": ["alert_id", "tenant_id"], "window": "30m"},
        "runbook": "docs/runbooks/isolation.md",
    }
    payload.update(overrides)
    return payload


def _complete_runbook() -> str:
    return (
        "# Isolation\n\n"
        "## Diagnosis\n"
        "Inspect structured audit events for `tenant_isolation_violation`.\n\n"
        "## Safe mitigation\n"
        "Abort the affected operation. Do not mutate via the run investigation view.\n\n"
        "## Verification\n"
        "Cross-tenant `GET /v1/admin/runs/{run_id}` returns 404 `not_found`.\n\n"
        "## Escalation\n"
        "Escalate to platform-security if a foreign tenant_id appeared in a query.\n\n"
        "## Close\n"
        "Alert is quiet for one full window and isolation checks pass.\n"
    )


def test_alert_without_owner_is_rejected(tmp_path: Path) -> None:
    """An alert that cannot page an owner is not actionable."""
    alert = _write_alert(tmp_path / "isolation.json", _complete_alert(owner=""))

    messages = [finding.message for finding in validate_alert(alert)]

    assert any("owner" in message for message in messages)


def test_alert_without_runbook_is_rejected(tmp_path: Path) -> None:
    """An alert without a runbook link has no safe action."""
    payload = _complete_alert()
    del payload["runbook"]
    alert = _write_alert(tmp_path / "isolation.json", payload)

    messages = [finding.message for finding in validate_alert(alert)]

    assert any("runbook" in message for message in messages)


def test_runbook_without_verification_is_rejected(tmp_path: Path) -> None:
    """A runbook that cannot be closed is incomplete."""
    runbook = tmp_path / "isolation.md"
    runbook.write_text(
        "# Isolation\n\n"
        "## Diagnosis\nInspect audit events.\n\n"
        "## Safe mitigation\nAbort the operation.\n\n"
        "## Escalation\nPage platform-security.\n\n"
        "## Close\nMark the incident resolved.\n",
        encoding="utf-8",
    )

    messages = [finding.message for finding in validate_runbook(runbook)]

    assert any("verification" in message.lower() for message in messages)


def test_complete_alert_and_runbook_are_accepted(tmp_path: Path) -> None:
    """A complete isolated pair must not produce a false positive."""
    runbooks = tmp_path / "runbooks"
    alerts = tmp_path / "alerts"
    runbooks.mkdir()
    (runbooks / "isolation.md").write_text(_complete_runbook(), encoding="utf-8")
    _write_alert(alerts / "isolation.json", _complete_alert())

    assert validate_tree(runbooks, alerts_dir=alerts) == []


def test_repository_defines_the_five_actionable_alerts() -> None:
    """Missing one of the five P07 alerts would leave an incident without a runbook."""
    findings = validate_tree(RUNBOOKS_DIR, alerts_dir=ALERTS_DIR, dashboards_dir=DASHBOARDS_DIR)
    assert findings == []

    alert_ids = {
        json.loads(path.read_text(encoding="utf-8"))["id"]
        for path in ALERTS_DIR.glob("*.json")
    }
    assert set(REQUIRED_ALERT_IDS) <= alert_ids
    assert {name for name in REQUIRED_RUNBOOKS} <= {path.name for path in RUNBOOKS_DIR.glob("*.md")}


def test_alerts_are_backend_neutral_and_have_required_fields() -> None:
    """Product destinations were not chosen; inventing them would bind a future adapter."""
    for path in sorted(ALERTS_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in FORBIDDEN_DESTINATION_KEYS:
            assert key not in payload, f"{path} invents destination field {key}"
        for field in ("owner", "severity", "window", "threshold", "dedupe", "runbook"):
            assert payload.get(field), f"{path} missing {field}"
        runbook = REPO_ROOT / str(payload["runbook"])
        assert runbook.is_file(), f"{path} runbook {payload['runbook']} does not exist"


def test_runbooks_forbid_investigation_mutations_and_tenant_slug_conditionals() -> None:
    """The admin view is read-only and Core cannot branch on institution slugs."""
    for path in (RUNBOOKS_DIR / name for name in REQUIRED_RUNBOOKS):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "post /admin/runs" not in lowered
        assert "patch /admin/runs" not in lowered
        assert "delete /admin/runs" not in lowered
        assert "tenant_slug ==" not in lowered
        assert "if tenant_slug" not in lowered
        assert "if slug ==" not in lowered
        for marker in PII_MARKERS:
            assert marker not in text


def test_tabletop_reconstructs_cause_and_mutations_without_free_text_pii() -> None:
    """AC-P07-010: reconstruct from structured IDs, never free-text logs of PII/secrets."""
    incident = json.loads(TABLETOP_PATH.read_text(encoding="utf-8"))
    result = reconstruct_tabletop(incident)

    assert result.cause
    assert result.mutations
    assert result.workflow_state == "manual_review_required"
    assert "appointments.create" in " ".join(result.mutations)
    rendered = result.render()
    for marker in PII_MARKERS:
        assert marker not in rendered
    assert "Juan Perez" not in rendered
    assert "Bearer" not in rendered


def test_tabletop_rejects_free_text_logs_that_contain_secrets() -> None:
    """Accepting a free-text log with a Bearer token would violate RF-036."""
    incident = {
        "incident_id": "tabletop-bad",
        "alert_id": "unknown-mutation-outcome",
        "run": {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
            "error_code": "upstream_timeout",
            "skill": "appointments.create",
        },
        "workflow": {"type": "create_appointment", "state": "manual_review_required"},
        "tools": [{"tool_name": "appointments.create", "error_code": "upstream_timeout"}],
        "free_text_logs": ["timeout for Juan Perez Bearer secret-token"],
    }

    messages = []
    try:
        reconstruct_tabletop(incident)
    except ValueError as exc:
        messages.append(str(exc))

    assert messages
    assert "free-text" in messages[0].lower() or "secret" in messages[0].lower()


def test_cli_accepts_the_repository_runbooks() -> None:
    """The documented gate command must exit 0 against the committed tree."""
    result = subprocess.run(
        [sys.executable, "scripts/verify_runbooks.py", "docs/runbooks"],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
