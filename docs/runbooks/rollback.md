# Rollback de config e integration

**Alerta:** `rollback-config-integration`  
**Owner:** `config-oncall`  
**Severidad:** high  
**Impacto:** una activación de config o un allowlist de integration degrada el tenant. El rollback es `ConfigurationService.activate` sobre una versión ya publicada, sin borrar auditoría.

Preflight exige `rollback_inputs`: tenant, `active_config_version` y channel integration presentes.

## Diagnóstico

1. Señales: `config_activation_error_count >= 1` en 10 minutos, o spike de `tool_error_ratio` / isolation inmediatamente después de un audit `activate` o `publish`.
2. Identificar el tenant por `tenant_id` y la versión: `config_version` en el run reciente vs `active_config_version`. No escribir el slug de la institución como regla.
3. Listar audit `publish` y `activate` con `version` y `actor_id`. Un rollback es un `activate` de una versión publicada anterior. La investigación de un run muestra `run.config_version` y no permite cambiarla.
4. Separar fallo de activate (versión inexistente → `not_found`) de config activa dañina (versión activa pero tools/isolation rotos).
5. Confirmar que existen inputs de rollback: fila de tenant, al menos una versión publicada anterior, mapping de channel integration. Si faltan, el preflight `rollback_inputs` ya falló y no hay rollback seguro.

## Mitigación segura

1. Activate la última versión publicada conocida-buena con un `TenantAdminContext` autorizado: `activate(admin, version)`. Eso actualiza `active_config_version` y escribe audit `activate`. No delete de `tenant_config` ni de `audit_event`.
2. Si el daño es solo la integration real, revertir el allowlist / feature flag del tenant en la versión activada. No introducir un condicional por nombre de institución en Core.
3. Jobs en vuelo conservan su payload y `schema_version`. No reescribir jobs viejos; el handler debe seguir siendo compatible durante la ventana.
4. No usar la vista de investigación para publish/activate. Esas mutaciones van por el servicio de configuration/onboarding.
5. Secretos: rotar solo si el incidente expuso un valor. El rollback de config no imprime `credentials_reference` resuelto.

## Verificación

1. `get_active` del tenant devuelve la versión activada. Nuevos runs en `GET /v1/admin/runs/{run_id}` muestran ese `config_version`.
2. Audit append-only contiene el `activate` de rollback con `version` y actor. Ningún evento fue borrado.
3. Preflight `rollback_inputs` pasa. `observability_isolation` no falla.
4. `config_activation_error_count` queda en 0 durante 10 minutos. Error rate de tools vuelve al nivel previo a la activación mala.
5. El otro tenant no cambió su `active_config_version`.

## Escalamiento

- `config-oncall` para activate/rollback.
- `platform-security` si la config mala rompió aislamiento (ver [isolation](isolation.md)).
- `integration-oncall` si hay que cortar el MCP (ver [upstream](upstream.md)).
- Legal si hubo exposición. `EXT-006` fija retención; este runbook no la redefine.

## Cierre

Cerrar cuando la versión buena está activa, el activate quedó auditado, el tenant ajeno no se tocó, y el alerta (dedupe 60 minutos, `alert_id` + `tenant_id`) está quieto. Evidencia: versiones e IDs de audit, no el payload de config si contiene referencias sensibles.
