# Criterios de aceptación — Fase 11

| ID | Criterio |
|---|---|
| AC-P11-001 | ADR-006 aceptado; fase 11 documentada; ADR-003 y ADR-005 sin enmienda |
| AC-P11-002 | `AnswerKind` sigue siendo `answer, clarify, insufficient, handoff`; `mypy --strict` verde sobre `src/ia_mcp/evals/runner.py` sin tocar sus chequeos `Never` |
| AC-P11-003 | `LLMPort.generate` admite devolver `ToolCallProposal`; una implementación que devuelve `LLMDecision` sigue siendo válida sin cambios |
| AC-P11-004 | Una `ToolCallProposal` ejecuta la tool vía `ToolExecutor` y provoca una segunda `llm.generate`; una decisión terminal provoca exactamente una |
| AC-P11-005 | El `ToolResult` vuelve en `LLMRequest.tool_results` saneado, enmarcado como evidencia no confiable, sin `upstream_reference` ni valores de credencial |
| AC-P11-006 | El turno se corta en `max_tool_iterations` con `insufficient` y `error_code="tool_budget_exhausted"`, y en el deadline con `turn_deadline_exceeded`; nunca con respuesta parcial |
| AC-P11-007 | Una tool canónica cuyo dispatch exige idempotency key no es invocable desde el turno; una tool descubierta no declarada tampoco; ambas responden `forbidden` sin invocar transporte |
| AC-P11-008 | `validation_error`, `not_found`, `conflict`, `contract_violation`, `upstream_timeout` y `upstream_unavailable` se realimentan como observación sin capa de retry en el harness; dos `forbidden` terminan en `handoff` |
| AC-P11-009 | `tenant_isolation_violation` aborta el turno sin realimentar nada al modelo y cierra el run `failed` con auditoría crítica |
| AC-P11-010 | Tenant A no ejecuta desde el loop una tool descubierta sólo en el MCP de tenant B; ninguna observación de un tenant aparece en el `LLMRequest` de otro; el executor se construye por turno desde el `TenantContext` del turno |
| AC-P11-011 | Un turno con una tool ejecutada emite `agent.run`, dos `llm.generate`, un `tool.execute` y un `mcp.resolve`; cada `ToolAuditEvent` lleva el `run_id` del turno y el `tenant_id` del `TenantContext` |
| AC-P11-012 | Cero condiciones por nombre o slug de institución en harness, executor y compiler; la suite FAQ y los datasets de eval existentes pasan sin cambio de expectativa |
