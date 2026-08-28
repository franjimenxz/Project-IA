# Criterios de aceptación — Fase 9

| ID | Criterio |
|---|---|
| AC-P09-001 | ADR-005 aceptado; ADR-003 enmendado; system TDD §13 y component model actualizados |
| AC-P09-002 | `available()` autoriza solo intersección discovered ∩ tenant ∩ skill; sin filtro deny-list `KNOWN_TOOLS` |
| AC-P09-003 | Tool descubierta, allowlisted por tenant y skill, invocable aunque no esté en `KNOWN_TOOLS` |
| AC-P09-004 | Tool no descubierta o fuera de allowlist tenant/skill → `forbidden` sin invocar transporte |
| AC-P09-005 | Cliente MCP implementa `tools/list` y `tools/call` con fake in-process; CI no requiere host LAN |
| AC-P09-006 | Host/scheme no allowlisted rechazado fail-closed; `http` solo si par explícitamente allowlisted |
| AC-P09-007 | Executor despacha `appointments.*` canónico a capability/workflow cuando está cableado |
| AC-P09-008 | Executor usa cliente genérico para tools autorizadas no canónicas |
| AC-P09-009 | Context compiler pasa catálogo descubierto como `server=` de `available()` y expone resultado en `CompiledContext.tool_schemas`; no usa `KNOWN_TOOLS` como server set |
| AC-P09-010 | Onboarding/evals no rechazan nombre solo por estar fuera de `KNOWN_TOOLS` |
| AC-P09-011 | Tenant A no autoriza tools descubiertas exclusivas de tenant B |
| AC-P09-012 | Toda invocación pública incluye `TenantContext`, audit y timeout |
