# Mutación con resultado desconocido

**Alerta:** `unknown-mutation-outcome`  
**Owner:** `workflow-oncall`  
**Severidad:** high  
**Impacto:** un tool mutable (`appointments.create` / `cancel` / `reschedule` / `confirm`) terminó en `upstream_timeout` u otro outcome no confirmado. El workflow debe quedar en `manual_review_required`, nunca en `completed`.

La investigación de runs reconstruye causa y mutaciones. No confirma el turno en el upstream ni marca éxito.

## Diagnóstico

1. Tomar `unknown_mutation_outcome_count` y los labels `workflow_type`, `tool_name`, `error_code`, `tenant_id`.
2. Con `operator`/`auditor` del tenant, leer `GET /v1/admin/runs/{run_id}`. Esperar:
   - `run.error_code` en `{upstream_timeout, upstream_unavailable}` o `manual_review_required`;
   - `workflow.state` / `status` = `manual_review_required`;
   - timeline UTC: `tool` → `retry` → `transition` a `manual_review_required`.
3. Anotar mutaciones por IDs: `workflow_id`, `tool_name`, `retry_count`, `mcp_server_id`, `command` implícito en transiciones. No leer message bodies ni `patient_reference`.
4. Si el read model muestra `completed` después de un timeout de create, tratarlo como defecto de contrato (AC-P04-027) además de incidente.
5. No reconstruir desde logs libres. Un tabletop válido usa el fixture estructurado, no prosa con nombres o tokens.

## Mitigación segura

1. No reenviar el command de mutación desde la vista ni a mano "para ver si pasó". El workflow ya aplicó compensación a `manual_review_required` cuando no hay rollback seguro.
2. No marcar el workflow `completed`. Un turno fantasma o un duplicado es peor que dejar review.
3. Si hay que consultar el upstream, hacerlo por el puerto de integration autorizado con la idempotency key del command, fuera de `/admin/runs`.
4. Handoff humano con reason `manual_review_required` si el tenant lo tiene habilitado. El resumen de handoff no copia notas clínicas ni PII completa.
5. Si el timeout es sistémico, seguir [upstream](upstream.md) y pausar nuevas mutaciones por feature flag / allowlist de integration, no con un branch por institución.

## Verificación

1. El workflow permanece `manual_review_required` hasta resolución humana auditada.
2. Replay del mismo `command_id` / idempotency key no crea un segundo appointment (contratos P03/P04).
3. `GET /v1/admin/runs/{run_id}` sigue sin bodies/prompts/payloads y el timeline no inventa un `completed`.
4. `unknown_mutation_outcome_count` no crece durante 10 minutos tras la mitigación, o los nuevos puntos están explicados por el mismo `workflow_id` en review.

## Escalamiento

- `workflow-oncall` para estado incierto de una mutación.
- `integration-oncall` si el MCP/upstream no responde (ver [upstream](upstream.md)).
- `platform-security` si el timeout expuso un payload crudo en logs.

## Cierre

Cerrar cuando un humano autorizó el desenlace (turno confirmado en upstream, o compensación), el audit registra la resolución, no hay duplicado, y la alerta dedupeada (30 minutos, key `alert_id` + `tenant_id` + `workflow_type`) queda quieta. El criterio de cierre es el estado del workflow y los IDs, no un log narrativo.
