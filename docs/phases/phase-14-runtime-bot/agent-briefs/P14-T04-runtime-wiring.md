# P14-T04 — Wiring del runtime

**Estado:** in_progress · **Wave:** W13 · **Depends on:** P14-T01, P14-T02 y P14-T03 `accepted`

`build_runtime` instancia `GeminiLLM` si el secreto existe, `LabKnowledgeSearch` si hay packages dir, y pasa el catálogo MCP de lectura como `server_tools`. Fail-closed a `FakeLLM` / `EmptyKnowledgeSearch` si faltan.

Commit: `feat: wire Gemini and lab knowledge into development runtime (P14-T04)`

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-007](../../../01-architecture/adr/ADR-007-admin-service-tokens-and-secret-resolution.md)
4. [ADR-010](../../../01-architecture/adr/ADR-010-gemini-runtime-llm.md)
5. [../TDD.md](../TDD.md)
6. [../acceptance-criteria.md](../acceptance-criteria.md) (AC-P14-008, AC-P14-009, AC-P14-010)
7. [../test-plan.md](../test-plan.md)
8. Código: `src/ia_mcp/api/composition.py`, `src/ia_mcp/llm/gemini.py` (existe tras T01), `src/ia_mcp/knowledge/lab_search.py` (existe tras T02), `src/ia_mcp/configuration/adapters/environment_secrets.py` (`environment_variable_for()`), `tests/unit/api/test_composition.py`

## Archivos permitidos

**Modificar:**

- `src/ia_mcp/api/composition.py`
- `tests/unit/api/test_composition.py`

**No tocar:**

- reimplementar Gemini o knowledge
- mutaciones, secretos en repo
- `docs/00-governance/delegation-board.md`
- `FakeLLM` en `ports.py`

## Interfaces

`build_runtime` permanece síncrono y con la misma firma. Cambia el interior:

1. Clave: `environ.get(environment_variable_for("sm://platform/llm/gemini"), "").strip()`. Si hay valor → `GeminiLLM(transport=..., api_key=valor)`. Si no → `FakeLLM(...)` actual. No llamar `SecretResolver.resolve` (async; lanza si falta).
2. Knowledge: si `tenant_packages_dir_from(environ)` tiene valor → `LabKnowledgeSearch(packages_dir=...)`. Si no → `EmptyKnowledgeSearch`.
3. Compiler: `server_tools=frozenset({"appointments.search", "appointments.get"})` (las que `FakeAppointmentCapability` puede ejecutar). El término tenant lo resuelve T03 desde `config.enabled_tools`. No hardcodear por slug.

No concatenar instrucciones. No loguear la clave. No poner `get_secret_value()` en un f-string.

Los tests existentes de `build_runtime` sin esas variables deben seguir verdes (`FakeLLM` + `EmptyKnowledgeSearch`).

## TDD

1. Rojo: environ con `IA_MCP_SECRET_PLATFORM_LLM_GEMINI="test-not-a-secret"` → el `llm` del harness es `GeminiLLM`.
2. Rojo: environ sin esa clave → `FakeLLM`, no excepción.
3. Rojo: packages dir presente → knowledge es `LabKnowledgeSearch`; ausente → `EmptyKnowledgeSearch`.
4. Wiring mínimo.
5. Verde.

## Verificación

```text
pytest tests/unit/api/test_composition.py -v
ruff check src/ia_mcp/api/composition.py tests/unit/api/test_composition.py
```

Criterios: AC-P14-008, AC-P14-009, AC-P14-010.

## Exclusiones

- No relanzar T01–T03.
- No editar el tablero.
- No usar una clave real en tests.
