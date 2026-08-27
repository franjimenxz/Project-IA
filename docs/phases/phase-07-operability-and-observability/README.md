# Fase 7 — Operabilidad y observabilidad

**Estado:** ready  
**Prerequisito:** telemetría base desde Fase 2 y runs reales de Fase 4

## Objetivo

Permitir investigar runs, responder incidentes y operar capacidad/SLIs sin depender de logs de texto.

## Entregables

- convención OTel completa;
- read model de investigación;
- API/admin view server-rendered;
- dashboards y alertas;
- SLOs/budgets;
- runbooks de upstream, queue, isolation, unknown outcome y rollback;
- política de sanitización/retención.

## Gate

Un operador autorizado reconstruye un run sintético completo, alerta tiene acción/runbook y la caída del exporter no rompe negocio.

