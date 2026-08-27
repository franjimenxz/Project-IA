# Fase 2 — Fundaciones técnicas

**Estado:** ready  
**Gate de entrada:** G0  
**Gate de salida:** G1

## Objetivo

Crear el esqueleto ejecutable, tenancy/configuración, persistencia, errores y observabilidad que necesitan todas las vertical slices.

## Entregables

- proyecto Python reproducible y CI;
- FastAPI con health/readiness;
- `TenantContext` y configuración versionada;
- PostgreSQL/Alembic con constraints tenant-scoped;
- puertos de secretos y stores;
- errores comunes;
- correlación OpenTelemetry y auditoría base;
- test harness con dos tenants.

## Exclusiones

RAG, LLM real, workflows de turnos, MCP real, handoff y scheduler de negocio.

## Gate

El bootstrap funciona desde checkout limpio; config se publica/captura por versión; acceso cruzado falla; un request genera correlación y errores sanitizados.

