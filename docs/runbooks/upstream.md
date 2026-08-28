# Caída de upstream

**Alerta:** `upstream-outage`  
**Owner:** `integration-oncall`  
**Severidad:** high  
**Impacto:** tools MCP fallan con `upstream_unavailable` o `upstream_timeout`. Readiness de esa dependency se degrada; el resto de la plataforma no debe entrar en restart loop.

No se inventa un destino de paging. El owner es el rol `integration-oncall`.

## Diagnóstico

1. Medir `tool_error_ratio` en 5 minutos para `error_code` en `{upstream_unavailable, upstream_timeout}` por `mcp_server_id` y `tool_name`. Threshold: proporción ≥ 0.10.
2. Separar lecturas (`appointments.search`) de mutaciones. Una búsqueda caída no autoriza a crear turnos.
3. En un run sintético o de fixture, `GET /v1/admin/runs/{run_id}` debe mostrar `tool.status` y `error_code` tipados, sin payload crudo.
4. Health: liveness de `api`/`worker` vs readiness de la dependency MCP. Una dependency no esencial degradada no reinicia toda la plataforma (TDD del sistema, despliegue).
5. Descartar cardinalidad ilegal: no agrupar por `run_id`, `conversation_id` ni `patient_id`.

## Mitigación segura

1. Fail closed: no completar workflows ni enviar recordatorios que dependan del upstream caído.
2. Las mutaciones inciertas siguen [unknown-outcome](unknown-outcome.md): `manual_review_required`.
3. Deshabilitar la integration afectada por el control de allowlist/config versionada del tenant. No hardcodear el slug de la institución en Core.
4. No aumentar retries por encima de la política del workflow. Retry solo en errores tipados como transitorios y operaciones seguras.
5. No pegar URLs firmadas, headers `Authorization` ni `credentials_reference` resueltos en el ticket.

## Verificación

1. `tool_error_ratio` para ese `mcp_server_id` cae por debajo de 0.10 durante una ventana de 5 minutos, o la integration quedó disabled y el ratio se mide solo sobre intentos autorizados restantes.
2. Nuevos workflows no pasan a `completed` con tools en timeout.
3. Readiness de la dependency refleja el corte; liveness de `api` y `worker` sigue sano.
4. Un operador del otro tenant no ve tools ni `mcp_server_id` ajenos en su investigación.

## Escalamiento

- `integration-oncall` para el MCP/adapter.
- `workflow-oncall` si hay mutaciones en review (ver [unknown-outcome](unknown-outcome.md)).
- `platform-oncall` si el corte satura la cola (ver [queue](queue.md)).

## Cierre

Cerrar cuando el upstream responde otra vez, o la integration permanece disabled de forma auditada, no hay éxitos inventados, y el alerta (`dedupe` 20 minutos por `alert_id` + `tenant_id` + `mcp_server_id` + `error_code`) está quieto. Conservar IDs de runs y tools, no responses del provider.
