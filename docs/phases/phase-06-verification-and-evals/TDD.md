# TDD — Verificación y evals

**ID:** TDD-P06-001  
**Estado:** ready  
**Requisitos:** RF-040, RNF-001–RNF-015

## Dataset de evals

Formato JSONL versionado:

```python
class EvalCase(BaseModel):
    case_id: str
    tenant_fixture: str
    config_version: int
    messages: tuple[EvalMessage, ...]
    allowed_sources: frozenset[str]
    forbidden_sources: frozenset[str]
    expected_skill: str
    allowed_tools: frozenset[str]
    forbidden_tools: frozenset[str]
    expected_workflow_state: str | None
    expected_outcome: EvalOutcome
    assertions: tuple[SemanticAssertion, ...]
```

No contiene datos reales. Corpus y conversaciones son sintéticos y cubren español rioplatense, errores, ambigüedad, typos, adversarial y multi-turn.

## Trayectoria observada

El runner captura input, tenant/config, compiled context summary, retrieval source IDs, skill, tool calls, workflow transitions, handoff y outcome. Reasoning privado del proveedor no se exige ni almacena.

## Scorers

- exact match para tenant, skill, tools y workflow state;
- set comparison para sources/tools;
- JSON schema para argumentos;
- groundedness por claims/source IDs;
- policy assertions para no invención/handoff;
- judge model opcional sólo para propiedades semánticas, calibrado contra labels humanos;
- latencia/usage como métricas, no criterio único.

## Umbrales iniciales

- tenant selection: 100%;
- forbidden source/tool: 0 ocurrencias;
- critical policy adherence: 100%;
- workflow/tool schema validity: 100%;
- intent/skill y groundedness: baseline medido en FakeLLM y umbral aprobado antes de modelo real;
- ningún promedio puede ocultar fallo de caso crítico.

## Seguridad/resiliencia

Security suite usa casos canario y prueba boundaries. Resilience suite inyecta fault determinista en DB, Redis, LLM, object store, MCP, channel y handoff, verificando estado final y recuperación.

## Performance

Escenarios: FAQ concurrente entre tenants, workflows largos, vector corpus creciente, queue burst y upstream lento. Budgets por span permiten ubicar regresión. Datos de negocio `EXT-007` fijan SLO final.

## Reporte

Artefacto JSON + resumen Markdown con commit, dataset hash, environment, versiones, resultados por categoría, regresiones, casos críticos, flakiness y decisión de gate.

## Waiver

Un waiver requiere ID, caso, riesgo, owner, expiración y condición de cierre. Aislamiento, secret leakage o mutación incorrecta no admiten waiver para producción.

