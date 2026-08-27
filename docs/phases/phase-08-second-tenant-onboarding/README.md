# Fase 8 — Segundo tenant y readiness

**Estado:** preparación ready después de Fase 4; activación bloqueada hasta G4 y cierres de Fases 6–7

**Gate preparatorio:** P04-T13 aceptada para package/validator/provision disabled

**Gate de activación:** G4, P06-T05 y P07-T04 aceptados

**Gate de salida:** G5

## Objetivo

Probar que una segunda institución se incorpora mediante configuración, conocimiento, secrets references e MCP, sin lógica específica en Core.

## Entregables

- tenant package declarativo;
- CLI/service de validate/provision/publish/activate/disable;
- ingestión/publicación de corpus;
- configuración MCP y capabilities;
- preflight y suite A/B;
- runbook de onboarding/rollback;
- informe de cambios al Core;

## Regla de arquitectura

Si onboarding requiere `if tenant`, fork de skill o contrato específico dentro de Core, se bloquea y se evalúa capacidad genérica/ADR.
