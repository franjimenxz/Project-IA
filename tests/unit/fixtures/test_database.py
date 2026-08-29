from __future__ import annotations

from pathlib import Path

from tests.fixtures.database import (
    DEFAULT_DATABASE_URL,
    TEST_DATABASE_URL_ENV,
    database_url,
)

TESTS_ROOT = Path(__file__).resolve().parents[2]
HELPER = TESTS_ROOT / "fixtures" / "database.py"


def test_environment_variable_overrides_the_default_dsn() -> None:
    override = "postgresql+psycopg://ci@127.0.0.1:5432/ia_mcp_ci"
    assert database_url({TEST_DATABASE_URL_ENV: override}) == override


def test_missing_or_blank_variable_falls_back_to_the_default_dsn() -> None:
    assert database_url({}) == DEFAULT_DATABASE_URL
    assert database_url({TEST_DATABASE_URL_ENV: "   "}) == DEFAULT_DATABASE_URL


def test_surrounding_whitespace_is_trimmed() -> None:
    override = "postgresql+psycopg://ci@127.0.0.1:5432/ia_mcp_ci"
    assert database_url({TEST_DATABASE_URL_ENV: f"  {override}\n"}) == override


def test_env_name_follows_the_repository_prefix() -> None:
    assert TEST_DATABASE_URL_ENV.startswith("IA_MCP_")


def test_default_dsn_is_defined_in_exactly_one_place() -> None:
    # A second copy of the literal is a suite CI can no longer redirect.
    offenders = [
        str(path.relative_to(TESTS_ROOT.parent))
        for path in sorted(TESTS_ROOT.rglob("*.py"))
        if path != HELPER and DEFAULT_DATABASE_URL in path.read_text("utf-8")
    ]
    assert offenders == []
