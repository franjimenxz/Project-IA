# Criterios de aceptación — Fase 10

| ID | Criterio |
|---|---|
| AC-P10-001 | `create_app(environment="test")` no auto-wirea harness/tenant/executor; los tests de simulated que solo inyectan `tenant_service` siguen en ACK |
| AC-P10-002 | Con `environment="development"` y `DATABASE_URL`, `create_app` deja `tenant_service`, `config_service`, `agent_harness` y `channel_integration_ids` en `app.state` |
| AC-P10-003 | Un POST `/v1/simulated/messages` autenticado contra esa app entra a `AgentHarness.handle_message` y responde `SimulatedTurnResponse` (incluye `run_id`), no un ACK vacío |
| AC-P10-004 | `ToolExecutor` de development se construye con resolver + `allowed_hosts` + `SseMcpClient`; sin esos tres no hay transporte genérico |
| AC-P10-005 | Ningún host, slug de instituto ni secret se hardcodea en Core; `TenantContext` en todo boundary tenant-scoped |
| AC-P10-006 | Production no monta simulated y no presenta fakes como runtime de producción |
