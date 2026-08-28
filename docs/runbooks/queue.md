# Backlog de cola

**Alerta:** `queue-backlog`  
**Owner:** `platform-oncall`  
**Severidad:** medium  
**Impacto:** jobs u outbox envejecen. Recordatorios se atrasan o un claim queda stale. PostgreSQL sigue siendo autoritativo; Redis perdido no debe borrar jobs.

Threshold interino hasta `EXT-007`: `queue_age_seconds >= 300` en 15 minutos. No es un SLO de producción.

## Diagnóstico

1. Leer `queue_age_seconds` y `queue_depth` por `status` (`pending`, `claimed`) y `tenant_id`. Companion: `worker_heartbeat_age_seconds`.
2. Distinguir backlog real de un lock stale: job `claimed` con `lock_expires_at` vencido vs muchos `pending` con `scheduled_for` en el pasado.
3. Para un job del incidente, usar la investigación del `run_id` correlacionado: `jobs[].type`, `status`, `attempts`, `scheduled_for`. No abrir `payload` ni el texto del reminder.
4. Verificar versión: un reschedule incrementa `schedule_version` y vuelve stale el claim/outbox anterior. Un "backlog" de la versión vieja puede ser skip esperado.
5. Exporter de telemetría caído (`telemetry_exporter_failure`) no es causa de backlog de negocio y no se "arregla" reenviando jobs.

## Mitigación segura

1. No despachar ni cancelar jobs desde `GET /admin/runs/{run_id}`. Esa vista no muta.
2. Si el worker no tiene heartbeat, restaurar el proceso `worker` (outbox, jobs, scheduler). No borrar la cola.
3. No rehacer `scheduled_for` a mano ni clonar un job: la identidad estable es `(tenant_id, type, business_key)`. Un insert extra genera duplicados.
4. Si el backlog es de un solo tenant por upstream lento, degradar esa integration ([upstream](upstream.md)) en lugar de acelerar retries.
5. No usar el slug del tenant como rama de código para "priorizar" la cola.

## Verificación

1. `queue_age_seconds` del tenant vuelve por debajo de 300 durante 15 minutos, o los jobs restantes están `skipped`/`cancelled` con reason de versión stale.
2. Métricas `reminder_sent_count` / `reminder_skipped_count` / `reminder_duplicate_count` no muestran una ráfaga de duplicados tras la mitigación.
3. `worker_heartbeat_age_seconds` está fresco.
4. Un job replayed conserva `correlation_id` y no crea un segundo `external_message_id` para la misma `business_key` + `schedule_version`.

## Escalamiento

- `platform-oncall` por worker/outbox.
- `integration-oncall` si el envío canal/upstream no drena (ver [upstream](upstream.md)).
- `workflow-oncall` si los jobs atrasados dejan mutaciones en review.

## Cierre

Cerrar cuando la edad y la profundidad están bajo umbral o explicadas por skips de versión, no hay duplicados de reminder, y el alerta (dedupe 30 minutos, `alert_id` + `tenant_id`) queda quieto. Adjuntar conteos e IDs de job, no el texto enviado al canal.
