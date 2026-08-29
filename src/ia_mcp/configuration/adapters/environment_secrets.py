"""Environment-backed `SecretResolver`.

No secret manager is available to this deployment, so the one real adapter maps
a reference to a process environment variable:

    sm://<path>  ->  IA_MCP_SECRET_<PATH>

`<PATH>` is the reference path upper-cased with every `/`, `-` and `.` turned
into `_`. `sm://tenant-b/mcp/appointments` therefore reads
`IA_MCP_SECRET_TENANT_B_MCP_APPOINTMENTS`.

Limits of that mapping, which a deployment must respect:

- **It collapses separators and case.** `sm://a/b`, `sm://a-b` and `sm://a.b`
  all name `IA_MCP_SECRET_A_B`, as do `sm://A/B` and `sm://a/b`. Two references
  that differ only in separators or case are the same variable; the adapter
  cannot tell them apart, so a deployment must not use both.
- **Its lifetime is the process.** A process environment is fixed at exec time,
  so rotating a value takes a restart. Nothing is cached beyond that: each
  resolution reads the mapping again, so an adapter backed by a real secret
  manager can replace this one without changing its callers.
- **It is not tenant-aware.** Like the port it implements, it resolves an
  opaque identifier; ownership is decided upstream.

The value is returned as `SecretStr` and is never logged, echoed in an error or
stripped: what the variable holds is what the caller compares against.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import SecretStr

from ia_mcp.configuration.secrets import SECRET_SCHEME, SecretResolutionError

ENVIRONMENT_PREFIX = "IA_MCP_SECRET_"
# A reference path is a conservative slug: letters, digits and the three
# separators the mapping folds. Anything else (whitespace, `..`, query strings)
# is refused instead of being silently normalized into another variable.
_PATH_RE = re.compile(r"[A-Za-z0-9]+(?:[./-][A-Za-z0-9]+)*")
_SEPARATOR_RE = re.compile(r"[./-]")


def environment_variable_for(reference: str) -> str:
    """Return the variable that holds `reference`, or fail closed."""
    if not reference.startswith(SECRET_SCHEME):
        raise SecretResolutionError(reference, code="invalid_reference")
    path = reference[len(SECRET_SCHEME) :]
    if _PATH_RE.fullmatch(path) is None:
        raise SecretResolutionError(reference, code="invalid_reference")
    return f"{ENVIRONMENT_PREFIX}{_SEPARATOR_RE.sub('_', path).upper()}"


class EnvironmentSecretResolver:
    """Resolves `sm://` references from a process environment mapping."""

    def __init__(self, environ: Mapping[str, str]) -> None:
        self._environ = environ

    async def resolve(self, reference: str) -> SecretStr:
        value = self._environ.get(environment_variable_for(reference), "")
        if not value.strip():
            raise SecretResolutionError(reference)
        return SecretStr(value)
