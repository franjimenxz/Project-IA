# ADR-005 — MCP discovery e invocación genérica

**Estado:** accepted  
**Fecha:** 2026-08-28  
**Supersedes:** ninguno  
**Amends:** [ADR-003](ADR-003-canonical-contracts-and-workflows.md)

## Contexto

Cada institución puede operar un MCP con su propio catálogo de tools (por ejemplo, un servidor con veinte tools en español). El Core no debe mantener un catálogo cerrado de nombres permitidos ni ramificar lógica por slug de tenant. Hasta ahora, `KNOWN_TOOLS` actuaba como intersección final y rechazaba cualquier nombre fuera de los seis tools canónicos de appointments, bloqueando MCPs institucionales reales.

ADR-003 sigue vigente para contratos Pydantic canónicos, fakes, workflows determinísticos y dispatch especializado cuando el nombre de tool coincide con la familia `appointments.*`. Esta decisión separa **autorización** (discovery + allowlists) de **contratos internos** (workflows y fakes).

## Decisión

1. **Resolución de target por tenant.** `McpResolver` devuelve `McpTarget` con server id, endpoint, auth *reference* (nunca el valor del secreto) y metadatos de transporte. El valor de credencial se resuelve en el adapter de secretos/transporte; no entra al LLM, logs ni fixtures.

2. **Discovery dinámico.** Tras resolver el target, el Core descubre tools mediante MCP `tools/list`. El catálogo descubierto es la fuente de verdad de nombres expuestos por ese servidor para el tenant.

3. **Autorización por intersección triple.** Una tool es invocable solo si su nombre pertenece a:
   - tools reportadas por `tools/list` del servidor resuelto;
   - allowlist de tools del tenant (`TenantConfig`);
   - allowlist de tools de la skill activa.

   No existe un enum cerrado de Core que niegue un nombre por no estar en `KNOWN_TOOLS`. `KNOWN_TOOLS` permanece como **alias set canónico** para workflows, fakes y dispatch especializado de appointments, no como deny-list global.

4. **Invocación genérica.** Las llamadas autorizadas usan MCP `tools/call` con `TenantContext`, auditoría, timeout y límites de tamaño. Si el nombre coincide con un tool canónico `appointments.*` y la capability está cableada, el executor puede seguir despachando a `AppointmentCapability`/workflows; cualquier otro nombre autorizado usa el cliente MCP genérico.

5. **Host/scheme fail-closed.** El resolver valida endpoint contra allowlist de host+scheme por tenant/entorno. `http` solo se permite si ese par host+scheme está explícitamente allowlisted (p. ej. MCP de prueba en LAN); no hay `http` abierto por defecto.

6. **Semántica de “tool desconocida”.** “Desconocida” significa **no presente en la intersección** (no descubierta, no allowlisted por tenant o no allowlisted por skill), no “ausente de un enum interno”.

## Consecuencias positivas

- Instituciones incorporan MCPs con catálogos propios sin cambios en Core.
- Autorización sigue siendo determinística y auditable.
- Workflows y contract tests de appointments conservan estabilidad vía ADR-003.
- LAN/test MCP puede operar con allowlist explícita sin relajar producción.

## Consecuencias negativas

- El Core depende de la salud y veracidad de `tools/list` en runtime.
- Validación estática de nombres en onboarding/evals debe relajarse respecto a `KNOWN_TOOLS`.
- Más superficie en cliente MCP (SSE, sesiones, timeouts).
- Tools no canónicas no pasan por workflows determinísticos salvo diseño explícito futuro.

## Alternativas descartadas

- **Catálogo cerrado en Core (`KNOWN_TOOLS` como deny-list):** impide MCPs institucionales reales y acopla Core al primer cliente.
- **`if tenant == instituto` en registry/executor:** viola multi-tenancy declarativa.
- **Inventar REST médico en Core:** fuera de scope; integración real sigue en Fase 5 vía adapter confirmado.
- **Exigir que todo MCP implemente los seis tools Pydantic de ADR-003:** incompatible con servidores existentes; reemplazado por discovery + allowlist.

## Verificación

- Unit: intersección triple sin filtro `KNOWN_TOOLS`; nombres descubiertos no canónicos autorizables cuando están en tenant/skill allowlist.
- Unit/integration: cliente MCP con fake in-process; CI no requiere host LAN externo.
- Security: host no allowlisted rechazado; tool fuera de intersección → `forbidden` sin invocar transporte.
- Regression: dispatch `appointments.*` a capability/workflow cuando está cableado.
- Onboarding/evals: nombre fuera de `KNOWN_TOOLS` no falla validación por sí solo.

## Rollback/sustitución

Revertir a filtro `KNOWN_TOOLS` en `available()` restauraría el comportamiento previo pero bloquearía MCPs institucionales. Rollback parcial: deshabilitar discovery y usar catálogo inyectado en config (modo degradado) mediante feature flag por tenant, documentado en runbook de integración.
