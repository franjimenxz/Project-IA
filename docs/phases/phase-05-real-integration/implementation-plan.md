# Real Institutional Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustituir el fake de appointments por un adapter institucional verificado contra sandbox.

**Architecture:** El adapter implementa `AppointmentCapability` y reutiliza transporte/auth/audit de MCP Platform. El Core no conoce la API.

**Tech Stack:** Python 3.13, Pydantic v2, HTTP client elegido por bootstrap, Pytest

**Spec:** `docs/phases/phase-05-real-integration/TDD.md`

## Global Constraints

- P05-T01 se desbloquea con P03-T05/P04-T10 aceptadas y EXT-001.
- P05-T02 requiere además EXT-003; P05-T03 requiere el transporte/auth aceptado.
- P05-T04 requiere P05-T03 aceptada y EXT-002.
- Sólo detalles citados por documentación oficial.
- Secrets nunca en fixtures.
- Cambios de contratos requieren ADR/versionado.

---

### Task 1: Intake y capability mapping

**Brief:** `agent-briefs/P05-T01-api-intake.md`

**Files:** Create `docs/phases/phase-05-real-integration/api-capability-mapping.md`, sanitized fixtures manifest.

- [ ] Verificar versión, autenticidad y alcance de documentación recibida.
- [ ] Mapear cada capability a contratos Fase 3 con citas a sección/página.
- [ ] Clasificar gaps como unsupported, compatible extension o contract conflict.
- [ ] Revisar mapping con owner institucional y arquitectura.
- [ ] Cambiar estado de tareas 2–4 a `ready` sólo con evidencia de gate.
- [ ] Commit `docs: map institutional API capabilities`.

### Task 2: Transporte y autenticación

**Brief:** `agent-briefs/P05-T02-transport-auth.md`

**Files:** Create institutional `transport.py`, `auth.py`, tests; secret adapter config.

- [ ] Escribir test con FakeTransport que afirma host allowlisted, auth aplicada y token ausente de repr/log.
- [ ] Ejecutar test; esperar imports faltantes.
- [ ] Implementar transport/auth exactamente según mapping aprobado, timeouts y redaction.
- [ ] Ejecutar unit/security tests con fault cases.
- [ ] Commit `feat: authenticate institutional MCP transport`.

### Task 3: Appointment adapter

**Brief:** `agent-briefs/P05-T03-appointment-adapter.md`

**Files:** Create `integrations/<institution>/appointments.py`, mapping functions, contract tests.

- [ ] Parametrizar contract suite con adapter y FakeTransport fixtures oficiales sanitizadas.
- [ ] Ejecutarla; esperar fallos de operaciones no implementadas.
- [ ] Implementar transformaciones puras y errores según mapping, una tool a la vez.
- [ ] Ejecutar contract/security/resilience suites.
- [ ] Commit `feat: adapt institutional appointment API`.

### Task 4: Sandbox, rollout y rollback

**Brief:** `agent-briefs/P05-T04-sandbox-rollout.md`

**Files:** Create sandbox tests, runbook and evidence reports; modify tenant integration config.

- [ ] Ejecutar reads sandbox con datos de prueba y capturar evidencia sanitizada.
- [ ] Ejecutar mutaciones controladas con idempotency/reconciliation.
- [ ] Ejecutar E2E workflows y aislamiento.
- [ ] Ensayar feature flag, abort, rollback y manejo de outcomes inciertos.
- [ ] Obtener aceptación de integración/seguridad/operaciones.
- [ ] Commit `test: verify institutional MCP in sandbox`.
