# TDD — Operabilidad y vista de runs

**ID:** TDD-P07-001  
**Estado:** ready  
**Requisitos:** RF-006, RF-034–RF-036, RF-044, RNF-003, RNF-004, RNF-006–RNF-008

## Read model

`RunInvestigation` agrega, mediante query service tenant-authorized:

```python
class RunInvestigation(BaseModel):
    run: RunSummary
    conversation: ConversationSummary
    retrievals: tuple[RetrievalSummary, ...]
    workflow: WorkflowSummary | None
    tools: tuple[ToolExecutionSummary, ...]
    handoff: HandoffSummary | None
    jobs: tuple[JobSummary, ...]
    audit_events: tuple[AuditEventSummary, ...]
    trace_url: AnyUrl | None
```

Summaries no contienen message bodies, chunks, prompts, tool payloads o patient identifiers completos. Source/resource IDs permiten acceso separado autorizado.

## API y view

- `GET /v1/admin/runs/{run_id}` JSON.
- `GET /admin/runs/{run_id}` HTML server-rendered accesible sólo a operator/auditor con tenant assignment.
- 404 uniforme para run inexistente o ajeno.
- paginación de events/tools y timestamps con timezone visible.

La vista presenta timeline, estados, errores, retries y links a trace. No permite ejecutar tools o editar estado.

## Telemetría

Semantic conventions propias versionadas; spans del observability strategy. Context propagation atraviesa outbox/jobs/MCP. Exporter async con queue/buffer acotado; falla genera métrica local y no bloquea negocio.

## Dashboards

- health/dependencies;
- agent and retrieval;
- workflows/tools;
- queues/jobs/reminders;
- handoff;
- per-tenant operational view con controles de acceso;
- security/isolation signals.

## Alertas/runbooks

Cada alerta tiene owner, severidad, ventana, threshold, dedupe y runbook. Runbook incluye diagnóstico, mitigación segura, verificación, escalamiento y cierre.

## Retención/acceso

RBAC y tenant scopes se aplican a read model, audit y dashboard. `EXT-006` fija períodos finales. Exportación/consulta se audita.

## Testing

Fixtures generan run completo, error, retry, handoff y job. Tests afirman timeline, redaction, 404 cross-tenant, RBAC, exporter failure y metric cardinality.

