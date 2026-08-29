"""Single source of truth for the PostgreSQL DSN the suites connect to.

Every suite that needs PostgreSQL imports `DATABASE_URL` from here instead of
repeating a literal, so CI (and any contributor whose local role or database
name differs) can point the whole test tree at another instance by exporting
`IA_MCP_TEST_DATABASE_URL`. The fallback is the repository owner's local DSN,
which keeps `pytest` working with no extra setup. The variable follows the
`IA_MCP_` prefix already used by `ia_mcp.api.composition` and `ia_mcp.api.app`.

The DSN is a connection string for a disposable test database: the suites drop
and recreate `public` on every run, so it must never point at real data. It is
not a secret and carries no password; a deployment DSN with credentials belongs
in the environment variable, never in this file.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

TEST_DATABASE_URL_ENV = "IA_MCP_TEST_DATABASE_URL"
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://francojimenez@127.0.0.1:5432/ia_mcp_p02_t03"
)


def database_url(environ: Mapping[str, str] | None = None) -> str:
    """Return the configured DSN, falling back to the local default."""
    source = os.environ if environ is None else environ
    return source.get(TEST_DATABASE_URL_ENV, "").strip() or DEFAULT_DATABASE_URL


DATABASE_URL = database_url()
