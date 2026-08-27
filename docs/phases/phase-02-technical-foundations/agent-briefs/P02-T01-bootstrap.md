# P02-T01 — Bootstrap FastAPI

**Estado:** ready  
**Wave:** W1  
**Objetivo:** checkout reproducible con `/health/live`, calidad y contenedores.

Leé TDD de fase, ADR-001 y testing strategy. Modificá sólo bootstrap, app base, test unitario, compose y CI. No agregues negocio, DB models ni proveedor LLM.

Archivos exactos: `pyproject.toml`, `src/ia_mcp/__init__.py`, `src/ia_mcp/api/app.py`, `tests/unit/api/test_app.py`, `compose.yaml` y `.github/workflows/quality.yml`.

Interfaz producida: `create_app() -> FastAPI`; `GET /health/live -> {"status":"alive"}`.

Ejecutá `ruff check . && mypy src && pytest tests/unit -v`. Handoff con commit `chore: bootstrap FastAPI platform` y AC-P02-001.
