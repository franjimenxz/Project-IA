# Plan de implementación — Fase 15

## Orden

```
P15-T01 Architecture docs     (coordinador)
                │
                ▼
P15-T02 Lab form + endpoint + chat WSP     accepted
                │
                ▼
P15-T03 Runtime adapt                      accepted
```

T02 y T03 no comparten archivos. T03 consume `lab_mcp.load_lab_mcp_endpoints` creado por T02.

## T01 — Docs

ADR-011, TDD, AC, briefs, tablero. Sin código de runtime.

## T02 — Form y mapa

`lab_mcp.py`, `InstitucionForm.mcp_endpoint`, templates, router HTML. Discovery inyectable. No editar harness ni executor.

## T03 — Runtime

FAQ, harness, compiler flag, executor, client `intersect_allowed`, composition merge. No editar templates ni `lab_package.py`.

## Verificación por tarea

Ver el brief. El coordinador no marca `accepted` sin evidencia de pytest de la tarea y, si toca docs, `check_docs` + `check_traceability`.
