# Fase 4 — MVP por vertical slices

**Estado:** ready  
**Gate de entrada:** G2  
**Gate de salida:** G3 por slice

## Objetivo

Demostrar la arquitectura con recorridos end-to-end sobre dos tenants y dependencias simuladas contractuales.

## Slices

| Slice | Resultado | Tareas |
|---|---|---|
| 4.1 | FAQ con PDFs, fuentes y aislamiento | P04-T01–P04-T05 |
| 4.2 | Creación de turno completa con mock MCP | P04-T06–P04-T08 |
| 4.3 | Cancelación, reprogramación y confirmación | P04-T09–P04-T10 |
| 4.4 | Human handoff y ownership | P04-T11 |
| 4.5 | Scheduler y recordatorio 48h | P04-T12 |
| Integración | Suite E2E y resiliencia conjunta | P04-T13 |

## Regla de entrega

Cada slice atraviesa canal simulado, tenant, runtime, persistencia, auditoría y respuesta. Una slice no se acepta con componentes aislados o una demo manual sin pruebas.

## Gate final

Dos tenants coexisten y ninguna prueba obtiene configuración, knowledge, estado, tools, secrets o auditoría del otro. Todos los workflows sobreviven reinicio y las mutaciones son idempotentes.

