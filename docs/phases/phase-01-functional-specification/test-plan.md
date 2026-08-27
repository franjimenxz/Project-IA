# Test Plan — Fase 1

**Estado:** ready

## Verificaciones

| ID | Verificación | Comando previsto | Oráculo |
|---|---|---|---|
| P01-DOC-001 | Links Markdown | `python scripts/check_docs.py --links docs` | exit 0 |
| P01-DOC-002 | IDs únicos | `python scripts/check_docs.py --ids docs` | sin duplicados |
| P01-DOC-003 | Cobertura RF/RNF | `python scripts/check_traceability.py` | 100% de `must` |
| P01-DOC-004 | Tokens no resueltos fuera de templates | `rg '\{\{' docs --glob '!templates/**'` | sin resultados |
| P01-DOC-005 | Palabras de placeholder | `python scripts/check_docs.py --placeholders docs` | sin hallazgos normativos |

## Revisión humana

- producto: flujos y reglas;
- arquitectura: límites y dependencias;
- seguridad: datos y aislamiento;
- QA: verificabilidad y criterios.

## Exit

AC-P01-001 a AC-P01-008 aceptados y checks documentales automatizados incorporados al bootstrap de Fase 2.

