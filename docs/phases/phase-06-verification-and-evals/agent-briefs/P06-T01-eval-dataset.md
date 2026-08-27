# P06-T01 — Dataset de evals

**Estado:** ready · **Wave:** W6

Creá schemas estrictos y dataset sintético: UC-01–10, tenants A/B, insuficiencia, tool forbidden, injection, timeout y handoff. No incluir datos reales/completions.

Validar IDs, allowed/forbidden disjoint, referencias existentes y hash. Comando `pytest tests/evals/unit/test_dataset.py -v && python -m ia_mcp.evals validate evals/datasets/mvp.jsonl`. Commit `test: define versioned agent eval dataset`.

## Lectura obligatoria

Testing strategy, `../TDD.md`, criteria AC-P06-001/003/004, use cases y Task 1 del plan.

## Archivos exactos e interfaces

Crear `src/ia_mcp/evals/models.py`, `validator.py`, `evals/datasets/mvp.jsonl`, `tests/evals/unit/test_dataset.py`. No llamar modelos ni incluir datos reales. Produce `EvalCase` y `validate_dataset(Path) -> DatasetValidationReport`.

## Rojo/verde y evidencia

Rojo: duplicate ID y allowed/forbidden overlap. Verde: comando anterior más mypy. Adjuntar dataset hash, distribución UC/tenant/adversarial y commit indicado.
