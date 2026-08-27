# Documentación de implementación — Plataforma IA-MCP

Este directorio es la fuente de verdad para diseñar, implementar, verificar y operar la plataforma de agentes conversacionales multi-tenant.

## Orden de lectura

### Para comprender el producto

1. [`00-governance/requirements-catalog.md`](00-governance/requirements-catalog.md)
2. [`phases/phase-01-functional-specification/README.md`](phases/phase-01-functional-specification/README.md)
3. [`phases/phase-01-functional-specification/acceptance-criteria.md`](phases/phase-01-functional-specification/acceptance-criteria.md)

### Para comprender la arquitectura

1. [`01-architecture/system-tdd.md`](01-architecture/system-tdd.md)
2. [`01-architecture/component-model.md`](01-architecture/component-model.md)
3. [`01-architecture/sequence-diagrams.md`](01-architecture/sequence-diagrams.md)
4. [`01-architecture/data-model.md`](01-architecture/data-model.md)
5. [`01-architecture/security-and-multitenancy.md`](01-architecture/security-and-multitenancy.md)

### Para coordinar implementación

1. [`00-governance/master-roadmap.md`](00-governance/master-roadmap.md)
2. [`00-governance/delegation-protocol.md`](00-governance/delegation-protocol.md)
3. [`00-governance/traceability-matrix.md`](00-governance/traceability-matrix.md)
4. `phases/<fase>/implementation-plan.md`
5. `phases/<fase>/agent-briefs/*.md`

### Para verificar y operar

1. [`01-architecture/testing-strategy.md`](01-architecture/testing-strategy.md)
2. [`01-architecture/observability-strategy.md`](01-architecture/observability-strategy.md)
3. [`00-governance/definition-of-done.md`](00-governance/definition-of-done.md)

## Convenciones

| Prefijo | Significado |
|---|---|
| `ACT-NN` | Actor |
| `UC-NN` | Caso de uso |
| `RF-NNN` | Requisito funcional |
| `RNF-NNN` | Requisito no funcional |
| `BR-NNN` | Regla de negocio |
| `CON-NNN` | Restricción |
| `EXT-NNN` | Dependencia externa |
| `ADR-NNN` | Decisión arquitectónica |
| `AC-PNN-NNN` | Criterio de aceptación de fase |
| `PNN-TNN` | Tarea delegable |

Los estados documentales son `draft`, `ready`, `in_progress`, `blocked`, `in_review`, `accepted` y `superseded`.

## Jerarquía normativa

Requisitos aprobados → ADRs → TDD del sistema → TDD de fase → contratos ejecutables → plan → brief.

Una contradicción se resuelve en el nivel superior; nunca mediante una desviación silenciosa dentro de una tarea.

## Estado del programa

La documentación define ocho fases. La API médica, el proveedor real de WhatsApp y la plataforma real de handoff son dependencias externas; el MVP trabaja con puertos y mocks hasta que sus gates estén satisfechos.

