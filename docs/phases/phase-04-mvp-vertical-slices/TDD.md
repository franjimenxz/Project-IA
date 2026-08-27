# TDD — MVP por vertical slices

**ID:** TDD-P04-001  
**Estado:** ready  
**Requisitos:** RF-001–RF-044 excepto integración real RF-027  
**ADRs:** ADR-001–ADR-004

## 1. Slice 4.1 — FAQ multi-tenant

### Flujo

`POST /v1/simulated/messages` persiste mensaje deduplicado, crea AgentRun, selecciona `faq`, compila contexto, busca knowledge por tenant, llama FakeLLM/LLM Port y persiste respuesta con source IDs.

### Componentes

- ConversationRepository y AgentRunRepository.
- SkillRegistry e IntentRouter determinista/fake.
- ContextCompiler con presupuesto.
- ObjectStore, Parser, Chunker, EmbeddingPort, KnowledgeRepository.
- FAQSkill y AnswerPolicy.
- Channel outbox.

### Ingestión

Pipeline: upload metadata → checksum/dedupe → parse PDF → chunk con posición/página → embed → guardar draft → publicar versión. Un fallo deja documento `failed` con error seguro y no publica chunks parciales.

### Retrieval

`search(tenant, query, limit)` filtra `tenant_id` y published antes de ranking, devuelve score, texto, document/page y source id. Un post-check aborta ante tenant mismatch.

### Respuesta

La FAQ sólo puede afirmar datos respaldados por hits. `AnswerPolicy` decide `answer`, `clarify`, `insufficient` o `handoff`. El modelo recibe documentos como datos delimitados y tools vacías para FAQ.

## 2. Slice 4.2 — Creación de turno

### Workflow

Estados:

```text
collecting_fields
→ searching_slots
→ awaiting_slot_selection
→ awaiting_confirmation
→ revalidating
→ creating
→ completed
```

Errores pueden volver a collecting/search, finalizar failed o pasar a `manual_review_required`.

### Datos configurables

`AppointmentPolicy.required_fields` ordena campos como name, document, specialty, practitioner, date range, coverage y email. El workflow sólo solicita los habilitados y valida mediante FieldSpec; no hardcodea obligatoriedad institucional.

### Idempotencia

Cada mensaje normalizado genera command id. La mutación `appointments.create` usa una idempotency key estable derivada del workflow y transition. Replays devuelven el resultado persistido.

### MCP

MCP Resolver selecciona FakeAppointmentCapability del tenant. El executor valida tool nuevamente, registra ToolExecution y sanitiza request/response summaries.

## 3. Slice 4.3 — Ciclo de vida

### Cancelación

Get → validar ownership/policy → confirmation → cancel idempotente. `already_cancelled` es éxito idempotente.

### Reprogramación

Get → search → selection → revalidate → reschedule. Si el adapter futuro sólo admite cancel+create, no se usa esa estrategia sin TDD específico porque puede dejar operación parcial.

### Confirmación

Get → validar pending → confirm idempotente. Ya confirmado devuelve éxito. Respuestas ambiguas piden aclaración.

## 4. Slice 4.4 — Handoff

Triggers tipados: `explicit_request`, `insufficient_knowledge`, `persistent_error`, `out_of_scope`, `policy`, `low_confidence`, `manual_review_required`.

`HandoffRequest` incluye conversation, patient reference permitida, reason, summary, collected fields, completed actions y active workflow. El resumen se genera estructuradamente y se sanitiza.

Al crear: persistir handoff/outbox y cambiar conversación a `human_owned` en una transacción. Reintentos usan business key. Mientras está activo, Harness no inicia mutaciones.

## 5. Slice 4.5 — Scheduler

Al crear/actualizar turno se emite evento para calcular `scheduled_for` según timezone/policy, default 48 horas. La identidad estable es tenant/appointment/reminder kind. Una actualización reemplaza `scheduled_for`, incrementa `schedule_version` y cancela/invalida entregas de versiones anteriores. Worker reclama con lock y versión, consulta estado, omite claims stale/confirmed/cancelled, crea outbox versionado y marca dispatched.

Clock es puerto. Delivery y command son idempotentes. Una respuesta del paciente entra por el canal normal y selecciona confirm workflow.

## 6. Consistencia y concurrencia

- optimistic lock en Conversation/SessionState/Workflow;
- unique external message por channel integration;
- unique command por workflow;
- unique tool idempotency key por tenant/tool;
- outbox para mensaje/handoff/job;
- procesamiento at-least-once con handlers idempotentes.

## 7. Observabilidad

Todas las slices crean spans, AgentRun, WorkflowTransition, ToolExecution y AuditEvent aplicables. No se guardan prompts completos. Source IDs, state names y error codes permiten reconstrucción.

## 8. Testing

Cada slice ejecuta dos tenants, replay, error y reinicio. Fake LLM produce decisiones estructuradas determinísticas; evals con modelo real pertenecen a Fase 6.

## 9. Rollout

Feature flags por tenant/slice. Primer tenant usa fake integrations; segundo tenant usa corpus/config diferente. Desactivar una slice elimina skill/tools del contexto sin borrar estado/audit.
