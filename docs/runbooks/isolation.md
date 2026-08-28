# Aislamiento entre tenants

**Alerta:** `isolation-violation`  
**Owner:** `platform-security`  
**Severidad:** critical  
**Impacto:** un `TenantContext` resolvió o leyó un recurso de otro tenant. Cualquier conteo mayor que cero es incidente.

La vista `GET /v1/admin/runs/{run_id}` y `GET /admin/runs/{run_id}` es de solo lectura. No ejecuta tools, no edita estado y no es un canal de mitigación.

## Diagnóstico

1. Confirmar la señal `isolation_violation_count` en la ventana de 5 minutos y el `tenant_id` opaco del alerta. No usar el slug de una institución como condición en Core ni en este procedimiento.
2. Con un `operator` o `auditor` asignado a ese tenant, abrir la investigación JSON (`GET /v1/admin/runs/{run_id}`) del `run_id` correlacionado si existe. El scope sale de `TenantContext` del principal; headers `X-Tenant-ID` / `X-Tenant-Slug` no cambian el tenant.
3. Reconstruir con IDs: `correlation_id`, `run_id`, `error_code=tenant_isolation_violation`, action de audit (`tenant_denied`, `integration_denied`, `tenant_isolation_violation`). No copiar bodies, prompts, chunks, payloads de tools ni identificadores de paciente.
4. Un run inexistente o ajeno debe devolver el mismo 404 `title=not_found` / `detail=Resource not found`. Si el 404 difiere entre missing y cross-tenant, tratarlo como fallo de aislamiento de la vista.
5. No abrir logs de texto libre. Si el único rastro es prosa con PII o secretos, detener la captura y usar audit sanitizado.

## Mitigación segura

1. Abortar la operación afectada. No reintentar el command que disparó la violación.
2. Preservar audit append-only. No borrar eventos ni "limpiar" filas para ocultar el cruce.
3. Si la violación involucra una integration o un MCP, deshabilitar esa integration por el control autorizado de config/onboarding del tenant (activate de una versión previa o allowlist), no desde la vista de investigación.
4. No rotar ni pegar secretos en el ticket. El adapter de secretos ya exige `credentials_reference`; el valor no debe aparecer en excepciones ni en este runbook.
5. No ramificar Core por el nombre de una institución. El aislamiento se aplica con `TenantContext` en cada boundary.

## Verificación

1. `GET /v1/admin/runs/{run_id}` con un operador del tenant A contra un run del tenant B devuelve 404 uniforme.
2. La misma consulta in-tenant con un `auditor` autorizado responde 200 y deja `run_investigation_queried`.
3. `isolation_violation_count` vuelve a 0 durante una ventana completa de 5 minutos.
4. Preflight `observability_isolation` del tenant no falla. No se observan hits ajenos en retrieval ni en config.

## Escalamiento

- `platform-security` si hubo lectura o escritura cross-tenant.
- Legal / privacidad (`EXT-006`) si un identificador de paciente o secreto pudo salir del tenant.
- `config-oncall` si hay que rollback de integration. No escalar a un producto de paging no elegido.

## Cierre

Cerrar cuando: la violación está acotada por `tenant_id` y `correlation_id`, la mitigación autorizada quedó auditada, el 404 cruzado es uniforme, y la alerta permanece quieta una ventana de dedupe (30 minutos). Adjuntar solo IDs y códigos, nunca el dato que se intentó aislar.
