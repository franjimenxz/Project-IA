# P06-T01 — Dataset de evals

**Estado:** ready · **Wave:** W6

Creá schemas estrictos y dataset sintético: UC-01–10, tenants A/B, insuficiencia, tool forbidden, injection, timeout y handoff. No incluir datos reales/completions.

Validar IDs, allowed/forbidden disjoint, referencias existentes y hash. Comando `pytest tests/evals/unit/test_dataset.py -v && python -m ia_mcp.evals validate evals/datasets/mvp.jsonl`. Commit `test: define versioned agent eval dataset`.

