# P03-T05 — ToolExecutor tenant-aware

**Estado:** ready  
**Wave:** W2  
**Plan:** `../implementation-plan.md`  
**Depends on:** P03-T03, P03-T04

## Objetivo y resultado

Crear el boundary que vuelve a autorizar una tool antes de resolver/llamar la capability. El test de tool denegada demuestra cero invocaciones al spy.

## Lectura obligatoria

`docs/01-architecture/system-tdd.md`, ADR-002, ADR-003, `../TDD.md`, `../acceptance-criteria.md` y el plan de fase.

## Archivos

Crear `src/ia_mcp/mcp/executor.py` y `tests/unit/mcp/test_executor.py`. Consumir sin modificar `mcp/registry.py` y capability Protocol. No implementar transporte, SQL o integración real.

## Interfaces

Consume `ToolRegistry.authorize`, `McpResolver` y capability ports. Produce `ToolExecutor.execute(TenantContext, UUID, ToolCall) -> ToolResult[Any]`.

## TDD y verificación

Escribir primero casos denied/unknown/cross-tenant/allowed, ejecutar `pytest tests/unit/mcp/test_executor.py -v` para rojo, implementar dispatch mínimo y ejecutar `pytest tests/unit/mcp tests/security/test_tool_contracts.py -v && mypy src/ia_mcp/mcp`.

## Evidencia y commit

Adjuntar comandos, AC-P03-005/006, prueba de spy no invocado y commit `feat: enforce tool authorization at execution`.

