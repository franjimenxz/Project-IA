# Composition root — Implementation Plan

**Goal:** El server de development ejecuta el turno simulated con el mismo grafo que los e2e inyectan.

**Spec:** `TDD.md` · Brief `agent-briefs/P10-T01-runtime-composition.md`

## Task 1

- [ ] Rojo: `create_app(environment="development")` + `DATABASE_URL` no deja harness; simulated no trae `run_id`.
- [ ] Verde: composition module + wire condicional + executor con cliente SSE fail-closed.
- [ ] Commit `feat: wire runtime collaborators in create_app`.
