# P05-T03 — Adapter appointments institucional

**Estado:** blocked · **Depends on:** P05-T01, P05-T02

Implementá AppointmentCapability mediante transformaciones puras citadas en mapping. No cambiar Core ni contratos silenciosamente.

La suite compartida es el oráculo. Cubrir response inválida, errores oficiales, idempotencia y unknown outcome. Commit `feat: adapt institutional appointment API`.

## Lectura obligatoria

Mapping aceptado, contracts TDD/ADRs, `../TDD.md`, criteria AC-P05-004–009 y Task 3.

## Archivos exactos

Crear `src/ia_mcp/integrations/<institution>/appointments.py`, `mappers.py`, sanitized fixtures y tests. No editar canonical contracts, workflow o tool registry.

## Interfaces y TDD

Implementa `AppointmentCapability` con `TenantContext` explícito y transport P05-T02. Rojo: parametrizar suite contra adapter/FakeTransport; verde una tool por vez con `pytest -m contract tests/contract/appointments --adapter institutional -v` más security/resilience. Entregar mapping row y fixture source por test.
