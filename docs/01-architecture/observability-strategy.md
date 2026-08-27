# Estrategia de observabilidad y auditoría

**Estado:** ready  
**Requisitos:** RF-006, RF-034–RF-036, RF-044, RNF-003, RNF-006

## Objetivo

Reconstruir qué ocurrió, detectar degradaciones y operar por tenant sin almacenar datos sensibles innecesarios.

## Identificadores

| ID | Alcance |
|---|---|
| `correlation_id` | Ingreso y cadena distribuida |
| `conversation_id` | Conversación persistente |
| `message_id` | Mensaje normalizado |
| `run_id` | Turno del Agent Harness |
| `workflow_id` | Operación transaccional |
| `tool_execution_id` | Tool call individual |
| `job_id` | Trabajo asíncrono |

Se propagan en contexto y headers internos. Los IDs de paciente no son identificadores de observabilidad.

## Trazas

Spans principales:

```text
channel.receive
tenant.resolve
conversation.load
agent.run
context.compile
knowledge.search
llm.generate
skill.route
workflow.advance
mcp.resolve
tool.execute
handoff.create
channel.send
scheduler.dispatch
```

Atributos permitidos: IDs opacos, tenant, config version, skill, workflow type/state, tool name, MCP server id, status/error code, retry count, source count, token counts y latencias.

No se registran prompts, completions, chunks, message bodies, DNI, email, teléfono, auth headers o payloads crudos por defecto.

## Métricas

### Plataforma

- request rate/error/duration;
- queue depth/age;
- DB pool y query duration;
- Redis errors;
- object store errors;
- worker heartbeat.

### Agente

- runs por estado/skill;
- context tokens y model latency;
- retrieval duration/hit count/insufficient rate;
- tool calls por tool/status;
- handoff rate/reason;
- unsupported-answer eval rate.

### Workflows

- starts/completions/failures;
- time in state;
- conflicts y duplicates;
- manual review rate;
- reminder scheduled/sent/skipped/duplicate.

Tenant puede ser label sólo si la cardinalidad y política lo permiten. Conversation, run, patient y document nunca son labels de métricas.

## Logs

JSON estructurado con timestamp, severity, service, environment, correlation/run IDs, tenant opaco, event name, outcome y error code. Mensajes libres se limitan; eventos conocidos usan schemas.

El redactor se ejecuta antes del sink. Logging failure no debe bloquear una mutación ya confirmada, pero genera métrica y fallback seguro local según política.

## Auditoría

Eventos mínimos:

- conversation started/ownership changed;
- tenant resolved/denied;
- config published/activated/rolled back;
- skill selected/denied;
- knowledge search con source IDs;
- workflow transition;
- tool requested/completed/failed;
- integration resolved/denied;
- handoff requested/accepted/resolved;
- job scheduled/dispatched/skipped;
- administrative access/change;
- isolation or security violation.

Audit metadata es sanitizada, append-only y consultable con RBAC. La auditoría registra quién, qué, sobre qué tenant/recurso, cuándo, resultado y motivo; no copia contenido completo.

## Vista de investigación

Una vista por `run_id` muestra:

- tenant y config version;
- conversation/message trigger;
- skill y workflow;
- retrieval source IDs;
- MCP y tools;
- transiciones y retries;
- handoff/job relacionados;
- estado, errores y latencias;
- enlaces a spans y audit events.

## Alertas iniciales

| Severidad | Señal |
|---|---|
| Critical | isolation violation, secret detection, audit persistence failure sostenida |
| High | mutación con estado incierto, contract violation, error rate de tools elevado |
| Medium | latency budget excedido, queue age, retrieval insufficient spike |
| Low | config validation failures, duplicate messages/jobs |

Cada alerta enlaza un runbook, owner, impacto y criterio de cierre. Se evitan alertas sin acción.

## SLOs

Fase 2 fija indicadores técnicos iniciales. Antes de producción `EXT-007` define objetivos aprobados para disponibilidad, latencia de primera respuesta, completion de workflow, entrega de recordatorios y tiempo de handoff.

## Retención

Logs operativos, traces, métricas, mensajes y auditoría tienen políticas separadas. `EXT-006` fija ventanas finales. La arquitectura admite borrado/anonymization por tenant y legal hold cuando corresponda.

## Pruebas

- un run E2E se reconstruye por IDs;
- errores tipados aparecen en trace, metric y audit sin payload sensible;
- retries conservan correlación;
- dos tenants no se mezclan en consultas operativas;
- redactor elimina secretos/PII conocidos;
- caída del exporter no rompe el flujo de negocio;
- cardinalidad de métricas permanece acotada.

