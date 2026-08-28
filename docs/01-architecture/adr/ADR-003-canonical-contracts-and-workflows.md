# ADR-003 — Contratos canónicos y workflows determinísticos

**Estado:** accepted  
**Fecha:** 2026-08-27  
**Amended by:** [ADR-005](ADR-005-mcp-discovery-and-generic-invoke.md) (2026-08-28)

> Los MCPs institucionales **no** están obligados a implementar los seis tools Pydantic canónicos de appointments. Discovery dinámico (`tools/list`) más intersección tenant/skill/server es el gate de autorización. ADR-003 sigue vigente para contratos canónicos internos, fakes, workflows determinísticos y dispatch especializado cuando el nombre de tool coincide con `appointments.*`.

## Contexto

Cada institución puede tener APIs diferentes. El LLM interpreta lenguaje, pero no debe decidir libremente validaciones, retries, idempotencia o mutaciones.

## Decisión

Definir contratos Pydantic canónicos para capacidades comunes y exigirlos a fakes, MCPs y adapters. Las operaciones mutables se ejecutan mediante workflows persistentes con state machine, commands idempotentes, outbox y errores tipados.

El LLM sólo propone intención/datos dentro de schemas; el workflow autoriza y ejecuta.

## Consecuencias positivas

- Core independiente de APIs institucionales.
- Contract tests reutilizables.
- Mutaciones auditables y recuperables.
- Fakes realistas antes de recibir API.

## Consecuencias negativas

- Transformaciones extra en adapters.
- Una API con semántica incompatible requiere decisión explícita.
- Versionado de contratos debe mantenerse.

## Alternativas descartadas

- Tool schemas iguales a cada API: acopla Core al primer cliente.
- LLM llama REST directamente: autorización y consistencia insuficientes.
- Workflow sólo en memoria: no recupera operaciones incompletas.

## Verificación

- fake y adapter ejecutan la misma contract suite;
- replay no duplica mutación;
- crash/restart recupera workflow;
- respuesta externa inválida falla como `contract_violation`.

