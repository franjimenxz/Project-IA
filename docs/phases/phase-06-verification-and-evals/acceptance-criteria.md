# Criterios de aceptación — Fase 6

| ID | Criterio |
|---|---|
| AC-P06-001 | Dataset JSONL valida schema, IDs únicos y sólo datos sintéticos |
| AC-P06-002 | Runner captura trayectoria sin prompt/reasoning privado completo |
| AC-P06-003 | Tenant, sources y tools prohibidos se evalúan con exactitud determinística |
| AC-P06-004 | Un caso crítico fallido hace fallar gate aunque el promedio supere umbral |
| AC-P06-005 | Evals comparan baseline/current y reportan regresión por categoría |
| AC-P06-006 | Suite de aislamiento cubre config, KB, secrets, tools, state, jobs y audit |
| AC-P06-007 | Fault injection demuestra retry, recovery o manual review sin doble mutación |
| AC-P06-008 | Carga reporta latencia por span, throughput, errors y queue age |
| AC-P06-009 | Reporte reproduce commit, dataset, model/config y environment |

