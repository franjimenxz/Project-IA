# Test Plan — Fase 13

| Suite | Comando | Criterios |
|---|---|---|
| Package de laboratorio | `pytest tests/unit/onboarding/test_lab_package.py -v` | AC-P13-002, AC-P13-008 |
| lab_enable | `pytest tests/unit/onboarding/test_lab_enable.py -v` | AC-P13-003 |
| HTML y lista | `pytest tests/unit/api/test_instituciones_html.py -v` | AC-P13-004, AC-P13-005, AC-P13-006 |
| Aislamiento | `pytest tests/security/test_instituciones_isolation.py -v` | AC-P13-007, AC-P13-008 |
| Controles estáticos | `ruff check src/ia_mcp/api src/ia_mcp/onboarding tests/unit/api/test_instituciones_html.py tests/unit/onboarding/test_lab_package.py tests/unit/onboarding/test_lab_enable.py tests/security/test_instituciones_isolation.py && mypy src/ia_mcp/api src/ia_mcp/onboarding` | AC-P13-008 |
| Documentación | `python scripts/check_docs.py --all docs && python scripts/check_traceability.py && pytest tests/docs -q` | AC-P13-001 |

## Pruebas negativas obligatorias

| Escenario | Resultado esperado |
|---|---|
| Form con `api_key` extra | rechazo `extra="forbid"` |
| `credentials_reference` que no es URI | `validate_package` rojo |
| Segunda `lab_enable` | un canal `simulated`; sin error |
| `IA_MCP_ENVIRONMENT=production` | rutas 404 / router ausente |
| Chat tenant A con canario de B en el store | respuesta y HTML sin el canario de B |
| Sin `Authorization` | 401, mismo mensaje que el resto del admin |
| `tenant_admin` de A pide slug B | 404 |
| Token en el body del form | no aparece en el HTML de respuesta |

## Fuera de CI

Ningún test llama a WhatsApp, LLM vendor ni host MCP externo.
