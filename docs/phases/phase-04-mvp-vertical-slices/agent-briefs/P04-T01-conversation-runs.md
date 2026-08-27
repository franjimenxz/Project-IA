# P04-T01 — Conversation y AgentRun

**Estado:** ready · **Wave:** W3 · **Depends on:** P02-T03, P02-T04

## Objetivo

Persistir conversaciones, mensajes, session state y runs tenant-scoped con deduplicación.

## Scope

Permitidos: `conversation/*`, `agent_runtime/run_repository.py`, migración y tests asociados. Excluidos: skills, LLM, knowledge y endpoints.

## Interfaces

Produce `ConversationRepository.receive(tenant, InboundMessage) -> ReceivedMessage` y `AgentRunRepository.start/finish`.

## Criterios/pruebas

AC-P04-002, 003, 007, 008. Probar duplicado, CAS, A→B not found y run config snapshot con PostgreSQL.

## Verificación/handoff

`pytest -m integration tests/integration/mvp/test_conversations.py -v && pytest -m security tests/security/test_tenant_isolation.py -v`. Commit `feat: persist tenant-scoped conversations and runs`.

