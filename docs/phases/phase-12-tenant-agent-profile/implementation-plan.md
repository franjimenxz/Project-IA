# Tenant Agent Profile Implementation Plan

**Goal:** Que el tono y las instrucciones opcionales del tenant lleguen a cada `LLMRequest` del turno, sin reemplazar Core ni abrir un system prompt libre.

**Architecture:** `TenantConfig.agent` → `CompiledContext.policies["agent"]` y, en cada `generate`, `LLMRequest.tone` / `LLMRequest.tenant_instructions`. Core viaja solo en `LLMRequest.instructions`.

**Tech Stack:** Python 3.13, Pydantic v2, Pytest

**Spec:** [`TDD.md`](TDD.md) · [ADR-008](../../01-architecture/adr/ADR-008-tenant-agent-profile.md)

## Restricciones globales

- `AnswerKind` no cambia; toda extensión es aditiva y con default.
- `CORE_INSTRUCTIONS` no se concatena con el texto del tenant.
- Sin condiciones por slug de institución en Core.
- `TenantContext` en todo boundary; una ejecución usa una sola `config_version` (BR-002).
- Sin `persona`, `system_prompt`, saludo, voz, avatar, vendor ni modelo por tenant.
- Sin secret values en docs, fixtures, logs, traces ni prompts.
- El workflow engine no se invoca desde el turno.

## Task 1: ADR-008 y documentación de fase

**Brief:** [`agent-briefs/P12-T01-architecture-docs.md`](agent-briefs/P12-T01-architecture-docs.md)

- [x] Rojo: el hueco (tone en config, ausente en `LLMRequest`) no está escrito en ningún ADR ni fase; revisión documental falla por falta de fuente normativa.
- [x] Verde: ADR-008, fase 12 con TDD, criterios, plan, test plan y brief de T02.
- [x] Commit `docs: define tenant agent profile and its path to the model`.

## Task 2: Contrato y cableado del perfil

**Brief:** [`agent-briefs/P12-T02-profile-contract.md`](agent-briefs/P12-T02-profile-contract.md)

- [x] Rojo: `AgentConfig` no acepta `instructions`; `LLMRequest` no transporta `tone` ni `tenant_instructions`; el harness no los copia.
- [x] Verde: campo opcional en `AgentConfig`, campos aditivos en `LLMRequest`, compiler y harness que copian el perfil, schema y fixture de tenant B, suite unitaria y de aislamiento.
- [x] Commit `feat: copy tenant agent profile to every LLM request`.

## Wave W11

T01 precede a T02. T02 es una sola tarea de implementación: contrato, compiler, harness, schema, fixture y pruebas. Un solo implementador después de las dos revisiones de T01.
