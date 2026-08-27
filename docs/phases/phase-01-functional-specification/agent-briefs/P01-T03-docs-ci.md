# P01-T03 — Gate documental en CI

**Estado:** ready  
**Wave:** W0  
**Depends on:** P01-T01, P01-T02

## Objetivo

Ejecutar validación documental, Ruff y tests docs en cada pull request.

## Archivos permitidos

`.github/workflows/quality.yml`, `pyproject.toml`, tests docs necesarios para CLI.

## Restricciones

Python 3.13; dependencias bloqueadas; no agregar servicios externos.

## Verificación

`python scripts/check_docs.py --all docs && pytest tests/docs -v && ruff check scripts tests/docs`.

## Handoff

Adjuntar workflow validado y commit `ci: enforce documentation quality`.

