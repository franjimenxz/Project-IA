# Fase 10 — Composition root

**Estado:** accepted  
**Objetivo:** que un proceso real (`create_app`) deje listos los mismos collaborators que hoy sólo inyectan los tests.

## Problema

`create_app` monta health, admin runs, outbox y el canal simulated. No instancia `tenant_service`, `config_service`, `agent_harness` ni `ToolExecutor`. Si el server arranca solo, `/v1/simulated/messages` autentica, resuelve tenant (si alguien inyectó el service) y devuelve `SimulatedMessageAck` sin entrar al harness.

## Fuera de alcance

WhatsApp (EXT-004), API médica real (EXT-001/002/003), consola `/demo`, y `create_onboarding_router` (residual P08-T03).
