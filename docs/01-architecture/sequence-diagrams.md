# Diagramas de secuencia

**Estado:** ready

## Consulta informativa

```mermaid
sequenceDiagram
    actor P as Paciente
    participant C as Channel Gateway
    participant T as Tenant Resolver
    participant H as Agent Harness
    participant K as Knowledge Service
    participant L as LLM Port
    participant A as Audit
    P->>C: mensaje FAQ
    C->>C: verificar + deduplicar
    C->>T: channel_account_id
    T-->>C: TenantContext
    C->>H: handle_message(tenant, message)
    H->>K: search(tenant, query)
    K-->>H: hits tenant-scoped + sources
    H->>L: contexto mínimo + evidencia
    L-->>H: respuesta estructurada
    H->>A: run/retrieval/result sanitizados
    H-->>C: AgentTurnResult
    C-->>P: respuesta + fuentes/fallback
```

## Crear turno

```mermaid
sequenceDiagram
    actor P as Paciente
    participant H as Agent Harness
    participant W as Workflow Engine
    participant M as MCP Resolver/Client
    participant X as Mock/External Agenda
    P->>H: solicita turno
    H->>W: start(create_appointment)
    W-->>H: campos faltantes
    H-->>P: solicita datos configurados
    P->>H: especialidad + rango
    H->>W: advance(command_id)
    W->>M: appointments.search
    M->>X: request adaptado
    X-->>M: slots
    M-->>W: AppointmentSlot[]
    W-->>H: alternativas
    H-->>P: presenta slots
    P->>H: selecciona + confirma
    H->>W: advance(selection, idempotency_key)
    W->>M: appointments.search/revalidate
    M-->>W: slot vigente
    W->>M: appointments.create
    M->>X: create idempotente
    X-->>M: appointment
    M-->>W: Appointment
    W-->>H: completed
    H-->>P: confirmación
```

## Cancelar turno

```mermaid
sequenceDiagram
    actor P as Paciente
    participant H as Harness
    participant W as Workflow
    participant M as MCP
    P->>H: cancelar turno
    H->>W: start(cancel)
    W->>M: appointments.get
    M-->>W: Appointment
    W-->>H: solicitar confirmación
    H-->>P: resumen + confirmar
    P->>H: confirma
    H->>W: advance(idempotency_key)
    W->>M: appointments.cancel
    M-->>W: cancelled / typed conflict
    W-->>H: resultado
    H-->>P: confirmación o alternativa segura
```

## Reprogramar turno

```mermaid
sequenceDiagram
    actor P as Paciente
    participant H as Harness
    participant W as Workflow
    participant M as MCP
    P->>H: reprogramar
    H->>W: start(reschedule)
    W->>M: appointments.get + search
    M-->>W: turno + alternativas
    W-->>H: opciones
    H-->>P: presenta slots
    P->>H: selecciona + confirma
    H->>W: advance(selection)
    W->>M: search/revalidate
    M-->>W: slot vigente
    W->>M: appointments.reschedule
    M-->>W: Appointment o estado incierto
    W-->>H: completed o manual_review_required
    H-->>P: resultado seguro
```

## Confirmación automática

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant DB as PostgreSQL/Outbox
    participant C as Channel Gateway
    actor P as Paciente
    participant H as Harness
    participant W as Workflow
    participant M as MCP
    S->>DB: claim reminder job
    S->>M: appointments.get
    M-->>S: pending confirmation
    S->>DB: outbox(send reminder)
    DB->>C: dispatch idempotente
    C-->>P: solicitar confirmación
    P->>C: confirma
    C->>H: inbound message
    H->>W: advance(confirm)
    W->>M: appointments.confirm
    M-->>W: confirmed
    W-->>H: completed
    H-->>P: acuse
```

## Human handoff

```mermaid
sequenceDiagram
    actor P as Paciente
    participant H as Harness
    participant O as Handoff Service
    participant Q as Operator Adapter
    actor A as Operador
    P->>H: solicita persona / trigger
    H->>O: create(summary, reason)
    O->>O: conversation=human_owned
    O->>Q: transfer payload
    Q-->>A: caso + contexto
    O-->>H: accepted
    H-->>P: derivación confirmada
    Note over H,O: mutaciones automáticas suspendidas
```

## Error del sistema externo

```mermaid
sequenceDiagram
    actor P as Paciente
    participant W as Workflow
    participant M as MCP Client
    participant X as External API
    participant O as Handoff
    W->>M: tool call + idempotency key
    M->>X: request con timeout
    X--xM: timeout/5xx
    M->>M: clasificar error
    alt operación retry-safe y presupuesto disponible
        M->>X: retry con backoff
        X-->>M: resultado
        M-->>W: ToolResult
    else estado incierto o retries agotados
        M-->>W: typed error
        W->>W: manual_review_required
        W->>O: handoff con acciones intentadas
        O-->>P: mensaje seguro
    end
```

## Propiedades comunes

- Todas las llamadas llevan tenant y correlation/run id.
- Toda mutación lleva command id e idempotency key.
- Cada boundary valida contratos y sanitiza observabilidad.
- Una respuesta externa inválida produce `contract_violation`; no se entrega al modelo como datos confiables.

