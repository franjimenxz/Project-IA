# Evidencia — Fase 12

Guardar:

- salida de `check_docs`, `check_traceability`, `pytest tests/docs` y `ruff check scripts tests/docs` (T01);
- contrato de `AgentConfig` e `LLMRequest`;
- compiler y harness copiando el perfil a cada `generate`;
- schema y fixture de tenant B sin secretos;
- suite negativa: el request de B no contiene el perfil de A;
- regresión FAQ sin cambio de expectativa.

No commitear credenciales, tokens ni payloads con PII.
