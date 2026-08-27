# Test Plan — Fase 6

| Área | Comando |
|---|---|
| Dataset/scorers | `pytest tests/evals/unit -v` |
| Fake deterministic eval | `python -m ia_mcp.evals run --suite smoke --provider fake` |
| Isolation | `pytest -m security tests/security/test_tenant_isolation.py -v` |
| Injection/data leakage | `pytest -m security tests/security/test_prompt_injection.py tests/security/test_redaction.py -v` |
| Resilience | `pytest -m resilience tests/resilience -v` |
| Performance | `python -m ia_mcp.performance run --scenario mvp-baseline` |
| Report gate | `python -m ia_mcp.evals compare --baseline evals/baselines/mvp.json --current build/evals.json` |

Model-real evals se ejecutan en entorno aprobado sin datos reales. Results no guardan completions salvo política explícita y redacción.

