# Test Plan — Fase 4

## Matriz por slice

| Slice | Unit | Integration | E2E | Security/resilience |
|---|---|---|---|---|
| 4.1 | compiler, policy, chunker | SQL/vector/object | message→answer | cross-tenant, injection, provider down |
| 4.2 | transitions, fields | workflow/outbox/MCP | request→create | replay, concurrency, timeout |
| 4.3 | state tables | tool lifecycle | cancel/reschedule/confirm | IDs ajenos, estado incierto |
| 4.4 | triggers/summary | ownership/outbox | request→operator fake | duplicate, provider down |
| 4.5 | time calculation | jobs/outbox | reminder→confirm | clock, replay, restart |

## Comandos

```bash
pytest tests/unit/agent tests/unit/knowledge tests/unit/workflows -v
pytest -m contract tests/contract -v
pytest -m integration tests/integration/mvp -v
pytest -m e2e tests/e2e/test_faq.py tests/e2e/test_appointments.py tests/e2e/test_handoff.py tests/e2e/test_reminders.py -v
pytest -m security tests/security/test_tenant_isolation.py tests/security/test_prompt_injection.py -v
pytest -m resilience tests/resilience/test_mvp_failures.py -v
```

## Fixtures

Tenants A/B, configs distintas, corpus canario, fake LLM, fake appointment MCP, fake handoff, fake channel, clock congelado, PostgreSQL/Redis/object store efímeros y fault plans.

## Exit

Todos los AC-P04 aplicables pasan, coverage de ramas críticas de state machines es completa, no hay sleep real y cada E2E produce run reconstruible.

