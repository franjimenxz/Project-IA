from __future__ import annotations

import json
from pathlib import Path

from ia_mcp.configuration.models import AgentConfig
from ia_mcp.onboarding.loader import load_yaml
from ia_mcp.onboarding.models import PackageConfig
from ia_mcp.onboarding.validator import validate_package
from tests.unit.onboarding.helpers import write_package

SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "ia_mcp"
    / "onboarding"
    / "schemas"
    / "tenant-package.schema.json"
)
TENANT_B_INSTRUCTIONS = (
    "No invente horarios ni especialidades que no figuren en el conocimiento recuperado."
)

FIXTURE_TENANT_B = (
    Path(__file__).resolve().parents[3] / "tenants" / "fixtures" / "tenant-b"
)


def test_package_rejects_secret_value(tmp_path: Path) -> None:
    package = write_package(tmp_path, integrations={"token": "plain-secret"})
    report = validate_package(package)
    assert report.valid is False
    assert "secret values are forbidden" in report.errors[0].message
    dumped = report.model_dump_json()
    assert "plain-secret" not in dumped


def test_package_rejects_invalid_cross_file_config(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        config={"knowledge": {"namespace": "other-tenant"}},
    )
    report = validate_package(package)
    assert report.valid is False
    assert any("namespace" in issue.message for issue in report.errors)


def test_package_rejects_extra_fields(tmp_path: Path) -> None:
    package = write_package(tmp_path, tenant={"unexpected_field": "nope"})
    report = validate_package(package)
    assert report.valid is False
    assert any("extra" in issue.message.lower() for issue in report.errors)


def test_package_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    package = write_package(tmp_path, tenant={"schema_version": 99})
    report = validate_package(package)
    assert report.valid is False
    assert any("schema_version" in issue.message for issue in report.errors)


def test_package_rejects_duplicate_channel_mapping(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        integrations={
            "channels": [
                {
                    "channel": "simulated",
                    "external_account_id": "tenant-b-simulated",
                    "secret_reference": "sm://tenant-b/channel/simulated",
                },
                {
                    "channel": "simulated",
                    "external_account_id": "tenant-b-simulated",
                    "secret_reference": "sm://tenant-b/channel/simulated-dup",
                },
            ]
        },
    )
    report = validate_package(package)
    assert report.valid is False
    assert any("channel" in issue.message.lower() for issue in report.errors)


def test_package_accepts_discovered_tool_name(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        config={
            "enabled_skills": ["faq", "appointments"],
            "enabled_tools": ["crear_turno", "appointments.search"],
        },
        integrations={
            "integrations": [
                {
                    "kind": "mcp",
                    "server_id": "fake-appointments-b",
                    "credentials_reference": "sm://tenant-b/mcp/appointments",
                    "capabilities": ["crear_turno", "appointments.search"],
                }
            ]
        },
    )
    report = validate_package(package)
    assert report.valid is True
    assert report.errors == ()


def test_package_rejects_tool_for_disabled_skill(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        config={
            "enabled_skills": ["faq"],
            "enabled_tools": ["appointments.search"],
        },
        policies={"faq": {"schema_version": 1, "skill": "faq"}},
    )
    report = validate_package(package)
    assert report.valid is False
    assert any(
        "skill" in issue.message.lower() or "tool" in issue.message.lower()
        for issue in report.errors
    )


def test_package_rejects_invalid_manifest_checksum(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        knowledge={
            "documents": [
                {
                    "logical_name": "hours-b",
                    "source": "object://synthetic/tenant-b/hours",
                    "checksum": "not-a-sha256",
                    "mime_type": "text/plain",
                }
            ]
        },
    )
    report = validate_package(package)
    assert report.valid is False
    assert any("checksum" in issue.message.lower() for issue in report.errors)


def test_secret_reference_is_validated_without_printing_value(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        integrations={
            "channels": [
                {
                    "channel": "simulated",
                    "external_account_id": "tenant-b-simulated",
                    "secret_reference": "sk-live-this-is-a-raw-token",
                }
            ]
        },
    )
    report = validate_package(package)
    assert report.valid is False
    dumped = report.model_dump_json()
    assert "sk-live-this-is-a-raw-token" not in dumped
    assert any("secret" in issue.message.lower() for issue in report.errors)


def test_content_hash_changes_when_secret_reference_uri_changes(tmp_path: Path) -> None:
    package_a = write_package(tmp_path / "a")
    package_b = write_package(
        tmp_path / "b",
        integrations={
            "channels": [
                {
                    "channel": "simulated",
                    "external_account_id": "tenant-b-simulated",
                    "secret_reference": "sm://tenant-b/channel/simulated-alt",
                }
            ]
        },
    )
    report_a = validate_package(package_a)
    report_b = validate_package(package_b)
    assert report_a.valid is True
    assert report_b.valid is True
    assert report_a.content_hash is not None
    assert report_b.content_hash is not None
    assert report_a.content_hash != report_b.content_hash
    dumped = report_a.model_dump_json() + report_b.model_dump_json()
    assert "plain-secret" not in dumped
    assert "sk-live-" not in dumped


def test_fixture_tenant_b_package_is_valid() -> None:
    report = validate_package(FIXTURE_TENANT_B)
    assert report.valid is True
    assert report.errors == ()


def test_package_without_agent_instructions_is_valid(tmp_path: Path) -> None:
    package = write_package(tmp_path)
    report = validate_package(package)
    assert report.valid is True
    assert report.errors == ()


def test_package_with_agent_instructions_is_valid(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        config={
            "agent": {
                "tone": "formal",
                "instructions": "Be precise about hours.",
            }
        },
    )
    report = validate_package(package)
    assert report.valid is True
    assert report.errors == ()


def test_package_rejects_agent_instructions_over_max_length(tmp_path: Path) -> None:
    package = write_package(
        tmp_path,
        config={"agent": {"tone": "formal", "instructions": "x" * 2001}},
    )
    report = validate_package(package)
    assert report.valid is False
    assert any(
        issue.code == "string_too_long"
        or "2000" in issue.message
        or "too long" in issue.message.lower()
        for issue in report.errors
    )


def test_package_config_agent_is_agent_config_not_a_parallel_type() -> None:
    assert PackageConfig.model_fields["agent"].annotation is AgentConfig
    import ia_mcp.onboarding.models as onboarding_models

    assert not hasattr(onboarding_models, "PackageAgentConfig")


def test_schema_allows_optional_agent_instructions() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    agent = schema["$defs"]["config"]["properties"]["agent"]
    assert agent["additionalProperties"] is False
    assert agent["required"] == ["tone"]
    instructions = agent["properties"]["instructions"]
    assert instructions["maxLength"] == 2000
    assert "string" in instructions["type"]
    assert "null" in instructions["type"]


def test_fixture_tenant_b_declares_policy_instructions_without_secrets() -> None:
    config = load_yaml((FIXTURE_TENANT_B / "config.yaml").read_text(encoding="utf-8"))
    assert config["agent"]["instructions"] == TENANT_B_INSTRUCTIONS
    dumped = json.dumps(config).lower()
    assert "sk-" not in dumped
    assert "password" not in dumped
    assert "api_key" not in dumped
    report = validate_package(FIXTURE_TENANT_B)
    assert report.valid is True
