# Fase 5 — Primera integración real

**Estado:** staged/blocking por tarea

**Gate de intake:** P03-T05 y P04-T10 aceptadas, y EXT-001 satisfecha

**Gate de transporte/auth:** P05-T01 aceptada y EXT-003 satisfecha

**Gate de sandbox:** P05-T03 aceptada y EXT-002 satisfecha

**Gate de salida:** G4

**Bloqueantes:** EXT-001, EXT-002, EXT-003

## Objetivo

Implementar el MCP/adaptador del primer instituto contra una API oficial, sin modificar los contratos del Core salvo necesidad genérica aprobada.

## Condiciones de desbloqueo progresivas

- P05-T01: documentación oficial versionada (`EXT-001`);
- P05-T02/P05-T03: autenticación, scopes, expiración y rate limits confirmados (`EXT-003`);
- P05-T04: sandbox y datos de prueba disponibles (`EXT-002`);
- contacto técnico/operativo para discrepancias.

## Trabajo permitido antes del desbloqueo

- ejecutar FakeAppointmentCapability;
- mantener contract suite;
- preparar intake/matriz de mapeo;
- validar red, secretos y observabilidad con stubs locales.

## Trabajo prohibido

Inventar endpoints, auth, requests, responses, códigos de error, idempotencia o semántica de reprogramación.
