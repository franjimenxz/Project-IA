# P05-T02 — Transporte y autenticación

**Estado:** blocked · **Depends on:** P05-T01 accepted, EXT-003

Implementá sólo mecanismo/hosts/timeouts confirmados. Permitidos: adapter institucional transport/auth y tests. Prohibido hardcodear secret o desactivar TLS.

Probar rotación, expiración, 401/403, redaction, SSRF/redirect y timeout. Commit `feat: authenticate institutional MCP transport`.

## Lectura obligatoria

Mapping P05-T01 aceptado, security TDD, `../TDD.md`, criteria AC-P05-003/006/009 y Task 2 del plan.

## Archivos exactos

Crear `src/ia_mcp/integrations/<institution>/transport.py`, `auth.py`, unit/security tests y config schema estrictamente citada. No modificar Core, contracts o fixtures con secrets.

## Interfaces y TDD

Consume `TenantContext`, SecretProvider, IntegrationPolicy y HTTP transport port; produce `InstitutionalTransport.request(...) -> ValidatedHttpResponse`. Rojo: FakeTransport assertions de allowlist/auth/redaction; verde: `pytest tests/unit/integrations/<institution>/test_transport.py tests/security/test_institutional_transport.py -v && mypy src/ia_mcp/integrations`. Evidence sin credenciales.
