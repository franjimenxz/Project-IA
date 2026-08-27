# Criterios de aceptación — Fase 5

| ID | Criterio Given / When / Then |
|---|---|
| AC-P05-001 | Dada cada tool, cuando se inspecciona mapping, entonces cada campo/endpoint/error enlaza fuente oficial |
| AC-P05-002 | Dadas discrepancias, cuando se decide mapping, entonces no se cambia Core sin ADR genérico |
| AC-P05-003 | Dada auth real, cuando se ejecuta adapter, entonces secret no aparece en config/prompt/log/trace |
| AC-P05-004 | Dado request canónico, cuando se transforma, entonces sandbox recibe formato oficial confirmado |
| AC-P05-005 | Dada response oficial, cuando se transforma, entonces cumple modelo canónico o contract_violation |
| AC-P05-006 | Dado timeout/retryable error, cuando policy aplica, entonces retries respetan seguridad y presupuesto |
| AC-P05-007 | Dada mutación con outcome incierto, cuando termina timeout, entonces workflow pasa a manual review |
| AC-P05-008 | Dada contract suite compartida, cuando corre contra sandbox adapter, entonces pasa sin branches del Core |
| AC-P05-009 | Dado tenant B, cuando se resuelve integration, entonces nunca usa endpoint/secrets de A |
| AC-P05-010 | Dado canary/rollback, cuando se activa/desactiva, entonces runs y mutaciones pendientes quedan reconciliables |

