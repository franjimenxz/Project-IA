# Test Plan — Fase 2

**Estado:** ready

| Suite | Casos | Comando |
|---|---|---|
| Unit | TenantContext, config validation, redactor, errors | `pytest tests/unit/tenancy tests/unit/configuration tests/unit/observability -v` |
| Integration | migrations, repositories, publish/activate/rollback | `pytest -m integration tests/integration/foundations -v` |
| Security | cross-tenant, secret leakage, spoofed tenant | `pytest -m security tests/security/test_foundations.py -v` |
| API | health y simulated envelope | `pytest tests/integration/api/test_health.py tests/integration/api/test_simulated_messages.py -v` |

Fixtures: PostgreSQL efímero, tenants A/B, channel accounts distintas, configs v1/v2, fake secret references y correlation id fijo.

Gate: migraciones up/down, suites anteriores, Ruff, tipos estrictos y documentación pasan desde checkout limpio.

