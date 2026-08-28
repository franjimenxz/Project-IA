# MCP Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Descubrir e invocar tools MCP institucionales sin catálogo cerrado en Core.

**Architecture:** Resolver → discovery (`tools/list`) → registry (intersección) → executor (canonical dispatch o generic `tools/call`).

**Tech Stack:** Python 3.13, Pydantic v2, httpx/SSE, Pytest

**Spec:** `docs/phases/phase-09-mcp-discovery/TDD.md`

## Global Constraints

- No `if tenant == instituto` en Core.
- No secret values en docs/fixtures/logs/LLM.
- `TenantContext` en todo boundary público.
- No reescribir dominio de Fases 6–8.
- ADR-003 workflows/fakes intactos para `appointments.*`.

---

### Task 1: Documentación y ADR-005

**Brief:** `agent-briefs/P09-T01-architecture-docs.md`

- [ ] Crear fase 9, ADR-005, enmienda ADR-003 y actualizaciones mínimas de governance/arquitectura.
- [ ] Commit `docs: define MCP discovery instead of closed tool catalog`.

### Task 2: Registry abierto

**Brief:** `agent-briefs/P09-T02-open-registry.md`

- [ ] Rojo: tool descubierta allowlisted invocable aunque no esté en `KNOWN_TOOLS`.
- [ ] Verde: quitar filtro deny-list; alinear skills, compiler, validators.
- [ ] Commit `feat: authorize discovered MCP tools by intersection`.

### Task 3: Discovery + cliente MCP

**Brief:** `agent-briefs/P09-T03-mcp-client.md`

- [ ] Rojo: fake in-process `tools/list` y `tools/call`.
- [ ] Verde: `discovery.py`, `client.py`, tests unitarios.
- [ ] Commit `feat: add MCP discovery and SSE client`.

### Task 4: Executor genérico

**Brief:** `agent-briefs/P09-T04-generic-executor.md`

- [ ] Rojo: tool no canónica autorizada usa generic client; canónica sigue capability.
- [ ] Verde: rama genérica en executor; regression appointments.
- [ ] Commit `feat: generic MCP tool invocation in executor`.

---

## Wave W8

T02 y T03 pueden ejecutarse en paralelo tras T01. T04 depende de T02 y T03.
