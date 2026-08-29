from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.check_tenant_specific_core import (
    classify_path,
    collect_range_files,
    find_slug_branches,
    review_changeset,
    review_repository,
)

CLEAN_CORE = "def score(hit):\n    return hit.score\n"
SLUG_BRANCH_CORE = (
    "def pick(tenant):\n"
    '    if tenant.tenant_slug == "tenant-b":\n'
    "        return 1\n"
    "    return 0\n"
)


def _git(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def _write(repository: Path, relative: str, content: str) -> None:
    path = repository / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "-A")
    _git(repository, "commit", "-m", message)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def onboarding_history(tmp_path: Path) -> tuple[Path, str, str]:
    """A repository whose history mirrors the second-tenant changeset.

    `base` predates the tenant package, `head` adds it without touching Core,
    and a later unrelated commit changes Core the way Phases 9 and 10 did.
    """
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.email", "tests@example.invalid")
    _git(repository, "config", "user.name", "Test Suite")
    _write(repository, "src/ia_mcp/skills/faq.py", CLEAN_CORE)
    base = _commit(repository, "base")
    _write(repository, "tenants/fixtures/tenant-c/config.yaml", "tone: formal\n")
    _write(repository, "tests/e2e/test_third_tenant.py", "assert True\n")
    _write(repository, "src/ia_mcp/onboarding/cli.py", "def main():\n    return 0\n")
    head = _commit(repository, "onboard tenant-c")
    _write(repository, "src/ia_mcp/mcp/executor.py", CLEAN_CORE)
    _commit(repository, "later core work")
    return repository, base, head


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
            "src/ia_mcp/onboarding/cli.py": "def default_onboarding_service():\n    return None\n",
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
    assert classify_path("src/ia_mcp/onboarding/cli.py") == "allowed"
    assert classify_path("src/ia_mcp/skills/cli.py") == "core"
    assert classify_path("src/ia_mcp/skills/faq.py") == "core"
    assert classify_path("tenants/fixtures/tenant-b/tenant.yaml") == "allowed"


def test_core_cli_outside_onboarding_is_still_scanned() -> None:
    findings = review_changeset(
        {
            "src/ia_mcp/skills/cli.py": (
                "def pick(tenant):\n"
                '    if tenant.tenant_slug == "tenant-b":\n'
                "        return 1\n"
                "    return 0\n"
            )
        }
    )
    assert findings
    assert any(item.code == "slug_branch" for item in findings)
    assert any(item.path == "src/ia_mcp/skills/cli.py" for item in findings)


def test_range_review_stays_green_as_later_commits_change_core(
    onboarding_history: tuple[Path, str, str],
) -> None:
    repository, base, head = onboarding_history
    changeset = collect_range_files(base, head, repository)
    assert set(changeset) == {
        "tenants/fixtures/tenant-c/config.yaml",
        "tests/e2e/test_third_tenant.py",
        "src/ia_mcp/onboarding/cli.py",
    }
    assert review_changeset(changeset) == ()


def test_range_review_reads_contents_from_the_head_commit(
    onboarding_history: tuple[Path, str, str],
) -> None:
    repository, base, head = onboarding_history
    (repository / "src" / "ia_mcp" / "onboarding" / "cli.py").write_text(
        SLUG_BRANCH_CORE, encoding="utf-8"
    )
    changeset = collect_range_files(base, head, repository)
    assert changeset["src/ia_mcp/onboarding/cli.py"] == "def main():\n    return 0\n"


def test_range_review_still_rejects_core_changes_inside_the_range(
    onboarding_history: tuple[Path, str, str],
) -> None:
    repository, base, _ = onboarding_history
    changeset = collect_range_files(base, "HEAD", repository)
    findings = review_changeset(changeset)
    assert any(item.path == "src/ia_mcp/mcp/executor.py" for item in findings)
    assert any(item.code == "core_change" for item in findings)


def test_range_review_does_not_blind_the_current_core_tree_scan(
    onboarding_history: tuple[Path, str, str],
) -> None:
    repository, base, head = onboarding_history
    assert review_repository(base, repository, head=head) == ()
    (repository / "src" / "ia_mcp" / "skills" / "faq.py").write_text(
        SLUG_BRANCH_CORE, encoding="utf-8"
    )
    findings = review_repository(base, repository, head=head)
    assert any(item.code == "slug_branch" for item in findings)
    assert any(item.path == "src/ia_mcp/skills/faq.py" for item in findings)
