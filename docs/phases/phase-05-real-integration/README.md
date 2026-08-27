# Fase 5 — Primera integración real

**Estado:** blocked  
**Gate de entrada:** Fase 3 aceptada, Slices 4.2–4.3 aceptadas y EXT-001–EXT-003 satisfechas

**Gate de salida:** G4

**Bloqueantes:** EXT-001, EXT-002, EXT-003

## Objetivo

Implementar el MCP/adaptador del primer instituto contra una API oficial, sin modificar los contratos del Core salvo necesidad genérica aprobada.

## Condición de desbloqueo

- documentación oficial versionada;
- sandbox y datos de prueba;
- autenticación, scopes, expiración y rate limits;
- contacto técnico/operativo para discrepancias.

## Trabajo permitido antes del desbloqueo

- ejecutar FakeAppointmentCapability;
- mantener contract suite;
- preparar intake/matriz de mapeo;
- validar red, secretos y observabilidad con stubs locales.

## Trabajo prohibido

Inventar endpoints, auth, requests, responses, códigos de error, idempotencia o semántica de reprogramación.
