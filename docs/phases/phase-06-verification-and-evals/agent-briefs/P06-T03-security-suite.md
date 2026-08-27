# P06-T03 — Suite de seguridad

**Estado:** ready · **Depends on:** Fase 4 integrada

Cubrir todos los stores/boundaries con matriz A/B, prompt injection, spoofing, SSRF, secret/PII redaction y tool escalation. Permitidos tests y controles puntuales de seguridad; cambios arquitectónicos se escalan.

Ejecutar security suite y scans. Commit `test: enforce cross-tenant security boundaries`.

## Lectura obligatoria

Security TDD/threat matrix, ADR-002, `../TDD.md`, AC-P06-006 y Phase 4 evidence.

## Archivos exactos e interfaces

Crear/expandir `tests/security/test_tenant_isolation.py`, `test_prompt_injection.py`, `test_redaction.py`, `fixtures/security_matrix.py`. Modificar controles productivos sólo en su módulo owner y con review; no silenciar excepciones.

## TDD/evidencia

Agregar primero un caso por config/KB/secret/tool/state/job/audit y observar fallo real; luego control mínimo. Verde: `pytest -m security tests/security -v` más scans configurados. Entregar matriz, AC-P06-006, cero critical waivers y commit.
