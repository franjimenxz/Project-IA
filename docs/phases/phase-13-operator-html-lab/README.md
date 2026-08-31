# Fase 13 — Páginas HTML de laboratorio

**Estado:** ready  
**Gate de entrada:** G6 satisfecho; Fase 12 aceptada en tablero  
**Salida de fase:** AC-P13-001–AC-P13-008 aceptados; sin gate global nuevo

## Problema

No hay página para crear, listar o configurar instituciones ni para probar el bot. El alta es paquete + CLI/HTTP. El HTML existente solo investiga un run. El canal simulado no es una UI.

## Objetivo

Páginas HTML simples (alta, edición, lista, chat tipo WhatsApp) en development/test, reutilizando provision, config y el harness, con `lab_enable` para que `capture()` funcione. El bot débil se mejora después.

## Entregables

- ADR-009;
- writer de package de laboratorio + `lab_enable`;
- HTML `/admin/instituciones` y `/admin/instituciones/{slug}/chat`;
- `GET /v1/admin/tenants`;
- suite unitaria y de aislamiento.

## Fuera de alcance

- `FakeLLM`, retrieval real, allowlist FAQ, WhatsApp real, API médica, PDFs.
- Campos institucionales no existentes.
- Activate productivo / preflight.
- Condiciones por slug en Core.
- Migraciones Alembic.

## Tareas

| ID | Resultado |
|---|---|
| [P13-T01](agent-briefs/P13-T01-instituciones-html.md) | Package writer, `lab_enable`, HTML y lista |

## Lectura obligatoria

- [ADR-002](../../01-architecture/adr/ADR-002-tenant-context-and-isolation.md)
- [ADR-007](../../01-architecture/adr/ADR-007-admin-service-tokens-and-secret-resolution.md)
- [ADR-009](../../01-architecture/adr/ADR-009-operator-html-lab.md)
- [TDD de fase](TDD.md)
- [Criterios](acceptance-criteria.md)
- [Spec](../../superpowers/specs/2026-08-31-operator-html-pages-design.md)
