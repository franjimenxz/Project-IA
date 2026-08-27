# Test Plan — Fase 8

| Suite | Comando |
|---|---|
| Package schema | `pytest tests/unit/onboarding -v` |
| Provision/idempotency | `pytest tests/integration/onboarding/test_provision.py -v` |
| Preflight | `pytest tests/integration/onboarding/test_preflight.py -v` |
| A/B E2E | `pytest -m e2e tests/e2e/test_second_tenant.py -v` |
| Isolation regression | `pytest -m security tests/security/test_tenant_isolation.py -v` |
| Core diff policy | `python scripts/check_tenant_specific_core.py --base <approved-baseline>` |

El baseline exacto se registra al iniciar onboarding, no se deja implícito. El script busca slugs, imports de tenant packages desde Core y branches por institución; revisión humana confirma cambios genéricos.

