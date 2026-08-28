from __future__ import annotations

from pathlib import Path

from ia_mcp.onboarding.validator import validate_package
from tests.unit.onboarding.helpers import write_package

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
