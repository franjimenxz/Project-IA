# P10-T01 — Runtime composition root

**Estado:** ready · **Wave:** W9 · **Depends on:** P09-T04 accepted

Cableá en `create_app` el grafo que hoy solo inyectan los tests: `tenant_service`, `config_service`, `agent_harness`, `channel_integration_ids` y `ToolExecutor` con `SseMcpClient`.

Commit: `feat: wire runtime collaborators in create_app`.

## Lectura obligatoria

1. `docs/README.md`
2. `docs/00-governance/delegation-protocol.md`
3. [ADR-005](../../../01-architecture/adr/ADR-005-mcp-discovery-and-generic-invoke.md)
4. [../TDD.md](../TDD.md)
5. [../acceptance-criteria.md](../acceptance-criteria.md)
6. Este brief
7. Código actual: `src/ia_mcp/api/app.py`, `src/ia_mcp/api/routes/simulated.py`, `tests/e2e/conftest.py`, `tests/integration/api/test_simulated_messages.py`, `src/ia_mcp/mcp/executor.py`, `src/ia_mcp/mcp/client.py`, `src/ia_mcp/onboarding/cli.py` (`DATABASE_URL`)

## Archivos exactos e interfaces

**Crear:**

- `src/ia_mcp/api/composition.py` — factory del grafo; sin lógica de dominio
- `src/ia_mcp/tenancy/adapters/sqlalchemy.py` — solo si no existe un `ChannelIntegrationRepository` SQL; la tabla `channel_integration` ya está en `configuration.adapters.sqlalchemy`
- `tests/unit/api/test_composition.py`

**Modificar:**

- `src/ia_mcp/api/app.py` — llamar composition según la tabla del TDD
- `tests/unit/api/test_app.py` / `tests/integration/api/test_simulated_messages.py` — solo si hace falta no romper ACK en `environment="test"`

**No tocar:**

- `docs/00-governance/delegation-board.md`
- consola `/demo` ni `src/ia_mcp/demo/`
- onboarding router / preflight ports
- contratos Pydantic de `TenantConfig` / `McpConfig` (escalar si hace falta `endpoint`)
- workflows, scheduling, WhatsApp, REST médico

## Comportamiento

```text
create_app(environment)
  test        → no auto-wire (inyección de tests intacta)
  production  → no simulated; no FakeLLM como prod
  development + DATABASE_URL → attach runtime
  development sin DATABASE_URL → no auto-wire

attach:
  tenant_service
  config_service
  agent_harness
  channel_integration_ids   # map (channel, account_id) -> UUID de channel_integration
  tool_executor             # resolver + allowed_hosts + SseMcpClient; capability fake solo dev
```

Nombres de `app.state` = los que ya lee `simulated.py`. Tests existentes que hacen `app.state.tenant_service = ...` después de `create_app(environment="test")` deben seguir pasando.

`channel_integration.id` existe en SQL pero no en el dataclass `ChannelIntegration`. No cambies ese contrato; poblá el dict de IDs desde el adapter SQL o un lookup aparte.

## TDD/evidencia

Rojo: development+`DATABASE_URL` sin harness, o simulated con runtime cableado sigue devolviendo ACK sin `run_id`.  
Verde: `uv run --extra quality pytest tests/unit/api/test_composition.py tests/unit/api/test_app.py tests/integration/api/test_simulated_messages.py tests/unit/mcp/test_executor.py -v && uv run --extra quality ruff check src/ia_mcp/api src/ia_mcp/tenancy && uv run --extra quality mypy src/ia_mcp/api/composition.py src/ia_mcp/api/app.py`

Criterios AC-P10-001–006.

## Exclusiones

- No inventar API, credenciales, auth, vendors LLM/embeddings ni campos institucionales.
- No hardcodear host MCP ni slug de instituto en Core.
- No pasar secretos al LLM, logs, traces o fixtures.
- No `if tenant_slug == "…"`.
- No PR, no push, no amend de commits ajenos, no editar el tablero.
- Commit en esta rama; handoff según `delegation-protocol.md`.
