from __future__ import annotations

from scripts.check_tenant_specific_core import (
    classify_path,
    find_slug_branches,
    review_changeset,
)


def test_core_tenant_slug_branch_is_rejected() -> None:
    findings = review_changeset(
        {
            "src/ia_mcp/skills/faq.py": (
                "def pick(tenant):\n"
                '    if tenant.tenant_slug == "tenant-b":\n'
                "        return 1\n"
                "    return 0\n"
            )
        }
    )
    assert findings
    assert any("slug" in item.message.lower() for item in findings)


def test_core_institution_name_branch_is_rejected() -> None:
    findings = review_changeset(
        {
            "src/ia_mcp/workflows/engine.py": (
                "def route(tenant):\n"
                '    if tenant.institution_name == "Clinic Norte":\n'
                "        return True\n"
                "    return False\n"
            )
        }
    )
    assert findings
    assert any("institution" in item.message.lower() for item in findings)


def test_isolation_slug_comparison_is_not_a_branch() -> None:
    source = (
        "if row is None or row.slug != identity.tenant_slug:\n"
        "    raise TenantIsolationViolation()\n"
    )
    assert find_slug_branches(source) == ()


def test_allowed_package_test_and_adapter_changeset_passes() -> None:
    findings = review_changeset(
        {
            "tenants/fixtures/tenant-b/config.yaml": "mcp:\n  server_id: fake-appointments-b\n",
            "tests/e2e/test_second_tenant.py": "assert True\n",
            "scripts/check_tenant_specific_core.py": "print('ok')\n",
            "docs/phases/phase-08-second-tenant-onboarding/evidence/P08-T04.md": "# ok\n",
            "src/ia_mcp/knowledge/adapters/object_store.py": "class InMemoryObjectStore:\n    pass\n",
        }
    )
    assert findings == ()


def test_core_file_change_is_rejected_even_without_slug_branch() -> None:
    findings = review_changeset(
        {
            "src/ia_mcp/skills/faq.py": "def score(hit):\n    return hit.score\n",
        }
    )
    assert any(item.code == "core_change" for item in findings)


def test_classify_adapters_as_allowed_and_skills_as_core() -> None:
    assert classify_path("src/ia_mcp/knowledge/adapters/sqlalchemy.py") == "allowed"
    assert classify_path("src/ia_mcp/skills/faq.py") == "core"
    assert classify_path("tenants/fixtures/tenant-b/tenant.yaml") == "allowed"
