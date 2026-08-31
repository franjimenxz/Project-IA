# Test Plan — Fase 12

| Suite | Comando | Criterios |
|---|---|---|
| Contrato de `AgentConfig` | `pytest tests/unit/configuration/test_agent_config.py -v` | AC-P12-002 |
| Contrato de `LLMRequest` | `pytest tests/unit/agent/test_models.py -v` | AC-P12-003 |
| Compiler y políticas | `pytest tests/unit/agent/test_context_compiler.py -v` | AC-P12-004 |
| Harness copia el perfil | `pytest tests/unit/agent/test_harness.py -v` | AC-P12-005, AC-P12-008 |
| Package y schema | `pytest tests/unit/onboarding/test_validator.py -v` | AC-P12-006, AC-P12-008 |
| Aislamiento del perfil | `pytest tests/security/test_agent_profile_isolation.py -v` | AC-P12-007, AC-P12-008 |
| Regresión FAQ | `pytest tests/unit/agent/test_harness.py tests/integration/mvp/test_faq_turn.py -v` | AC-P12-008 |
| Controles estáticos | `ruff check src tests && mypy src/ia_mcp/configuration src/ia_mcp/agent_runtime src/ia_mcp/onboarding` | AC-P12-002, AC-P12-003, AC-P12-008 |
| Documentación | `python scripts/check_docs.py --all docs && python scripts/check_traceability.py && pytest tests/docs -q` | AC-P12-001 |

Las rutas de suites nuevas se confirman contra el layout real de `tests/` al abrir T02; si una ya existe, la prueba se agrega ahí en lugar de crear un archivo paralelo. `tests/unit/agent/test_models.py` y `tests/unit/configuration/test_agent_config.py` no existen en el commit base; T02 los crea. `tests/unit/agent/test_harness.py` y `tests/unit/agent/test_context_compiler.py` se amplían.

## Pruebas negativas obligatorias

| Escenario | Resultado esperado |
|---|---|
| Tenant A con `tone`/`instructions` canario y tenant B con otros | El `LLMRequest` de B no contiene los canarios de A |
| `AgentConfig` con `persona` o `system_prompt` | Validación rechaza extra |
| `instructions` de 2001 caracteres | Validación rechaza |
| `instructions` `None` o `""` | Policies sin clave `instructions`; `tenant_instructions is None` |
| Package sin `agent.instructions` | `validate_package` válido |
| Texto del tenant igual a un fragmento de Core | `LLMRequest.instructions` sigue siendo exactamente `CORE_INSTRUCTIONS`; el texto del tenant va en `tenant_instructions` |
| Knowledge hit que pretende dar tono | El hit viaja en `knowledge` como EVIDENCE; no pisa `tone` ni `tenant_instructions` |
| Constructor de `LLMRequest` sin los campos nuevos | Tipa; defaults `tone=""` y `tenant_instructions=None` |

## Fuera de CI

Ningún test depende de un proveedor LLM real ni de un host MCP externo. `FakeLLM` sigue siendo el puerto en CI.
