"""Lab package writer (AC-P13-002, AC-P13-008).

No PostgreSQL: this suite only writes files and runs `validate_package`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ia_mcp.mcp.registry import KNOWN_TOOLS
from ia_mcp.onboarding.lab_package import InstitucionForm, write_lab_package
from ia_mcp.onboarding.loader import load_package, load_yaml
from ia_mcp.onboarding.validator import validate_package

TOKEN_CANARY = "sk-live-lab-token-must-not-appear"


def _form(**overrides: object) -> InstitucionForm:
    payload: dict[str, object] = {
        "slug": "clinica-norte",
        "display_name": "Clinica Norte",
        "tone": "formal",
        "instructions": "No invente horarios.",
        "enabled_skills": frozenset({"faq", "appointments"}),
        "enabled_tools": frozenset(
            {"appointments.search", "appointments.get", "appointments.create"}
        ),
        "mcp_server_id": "fake-appointments-norte",
        "mcp_capabilities": frozenset(
            {"appointments.search", "appointments.get", "appointments.create"}
        ),
        "mcp_credentials_reference": "sm://clinica-norte/mcp/appointments",
    }
    payload.update(overrides)
    return InstitucionForm.model_validate(payload)


def test_write_lab_package_is_accepted_by_validate_package(tmp_path: Path) -> None:
    package = write_lab_package(tmp_path, _form())
    report = validate_package(package)
    assert report.valid is True
    assert report.errors == ()
    assert package == tmp_path / "clinica-norte"


def test_write_lab_package_generates_simulated_channel_and_namespace(
    tmp_path: Path,
) -> None:
    package = write_lab_package(tmp_path, _form())
    loaded = load_package(package)
    tenant = load_yaml((package / "tenant.yaml").read_text(encoding="utf-8"))
    config = load_yaml((package / "config.yaml").read_text(encoding="utf-8"))
    integrations = load_yaml((package / "integrations.yaml").read_text(encoding="utf-8"))
    knowledge = load_yaml((package / "knowledge" / "manifest.yaml").read_text(encoding="utf-8"))
    assert tenant["slug"] == "clinica-norte"
    assert tenant["display_name"] == "Clinica Norte"
    assert config["knowledge"]["namespace"] == "clinica-norte"
    assert knowledge["namespace"] == "clinica-norte"
    assert config["feature_flags"]["simulated_channel"] is True
    assert config["mcp"]["server_id"] == "fake-appointments-norte"
    channel = integrations["channels"][0]
    assert channel["channel"] == "simulated"
    assert channel["external_account_id"] == "clinica-norte-simulated"
    assert channel["secret_reference"] == "sm://clinica-norte/channel/simulated"
    assert set(loaded.policies) == {"faq", "appointments"}
    assert loaded.evals == []
    dumped = (package / "evals.jsonl").read_text(encoding="utf-8")
    assert dumped.strip() == ""


def test_blank_instructions_are_omitted_from_agent_config(tmp_path: Path) -> None:
    package = write_lab_package(tmp_path, _form(instructions=""))
    config = load_yaml((package / "config.yaml").read_text(encoding="utf-8"))
    assert "instructions" not in config["agent"]
    report = validate_package(package)
    assert report.valid is True


def test_form_rejects_unknown_extra_fields() -> None:
    with pytest.raises(ValidationError) as refused:
        InstitucionForm.model_validate(
            {
                "slug": "clinica-norte",
                "display_name": "Clinica Norte",
                "tone": "formal",
                "mcp_server_id": "fake",
                "mcp_credentials_reference": "sm://clinica-norte/mcp/appointments",
                "api_key": TOKEN_CANARY,
            }
        )
    assert "api_key" in str(refused.value)
    assert TOKEN_CANARY not in str(refused.value)


def test_form_rejects_non_uri_credentials_reference() -> None:
    with pytest.raises(ValidationError):
        _form(mcp_credentials_reference="plain-secret-value")


def test_write_lab_package_rejects_non_uri_reference_for_validate_package(
    tmp_path: Path,
) -> None:
    """A credentials_reference that is not a URI must not become a valid package."""
    with pytest.raises(ValidationError):
        write_lab_package(
            tmp_path,
            _form(mcp_credentials_reference="not-a-uri"),
        )


def test_enabled_tools_must_be_known_and_declared_capabilities() -> None:
    with pytest.raises(ValidationError):
        _form(
            enabled_tools=frozenset({"appointments.search", "invented.tool"}),
            mcp_capabilities=frozenset({"appointments.search", "invented.tool"}),
        )
    with pytest.raises(ValidationError):
        _form(
            enabled_tools=frozenset({"appointments.search"}),
            mcp_capabilities=frozenset({"appointments.get"}),
        )
    allowed = set(KNOWN_TOOLS)
    assert "appointments.search" in allowed


def test_written_package_does_not_contain_secret_literals(tmp_path: Path) -> None:
    package = write_lab_package(tmp_path, _form())
    report = validate_package(package)
    assert report.valid is True
    blob = ""
    for path in package.rglob("*"):
        if path.is_file():
            blob += path.read_text(encoding="utf-8")
    assert TOKEN_CANARY not in blob
    assert "api_key" not in blob
    assert "plain-secret" not in blob


def test_knowledge_text_is_written_as_package_txt(tmp_path: Path) -> None:
    package = write_lab_package(
        tmp_path,
        _form(knowledge_text="Horario de 8 a 16."),
    )
    notes = list((package / "knowledge").glob("*.txt"))
    assert len(notes) == 1
    assert "Horario de 8 a 16." in notes[0].read_text(encoding="utf-8")
    assert validate_package(package).valid is True
