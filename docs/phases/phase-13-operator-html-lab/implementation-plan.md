# Operator HTML Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Páginas HTML para crear, configurar, listar y probar instituciones en development/test.

**Architecture:** El form escribe un package válido, `provision`/`publish` persisten, `lab_enable` deja `capture()` usable, el chat llama `AgentHarness` con el `TenantContext` del slug.

**Tech Stack:** Python 3.13, FastAPI, HTML templates, Pytest

**Spec:** [`TDD.md`](TDD.md) · [ADR-009](../../01-architecture/adr/ADR-009-operator-html-lab.md) · [`docs/superpowers/specs/2026-08-31-operator-html-pages-design.md`](../../superpowers/specs/2026-08-31-operator-html-pages-design.md)

## Restricciones globales

- Sólo `development` y `test`.
- Campos del package actual; `extra="forbid"`.
- `TenantContext` en todo boundary tenant-scoped.
- Sin secretos en HTML, logs ni fixtures.
- Sin `if tenant.slug` en Core.
- `FakeLLM`, preflight productivo y WhatsApp real no se tocan.

## Task 1: Package writer, lab_enable y HTML

**Brief:** [`agent-briefs/P13-T01-instituciones-html.md`](agent-briefs/P13-T01-instituciones-html.md)

- [ ] Rojo: no existe `write_lab_package` / `lab_enable` / rutas `/admin/instituciones`.
- [ ] Verde: package válido, lab_enable idempotente, HTML lista/alta/chat, aislamiento A/B, 401, ausente en production.
- [ ] Commit `feat: add lab HTML pages for institutions and try-chat`.
