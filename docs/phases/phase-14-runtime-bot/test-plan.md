# Plan de pruebas — Fase 14

## Unidad

| Caso | Archivo | AC |
|---|---|---|
| Texto + source_ids válidos → `LLMDecision` | `tests/unit/llm/test_gemini.py` | AC-P14-001 |
| `functionCall` allowlisted → `ToolCallProposal` | `tests/unit/llm/test_gemini.py` | AC-P14-002 |
| HTTP error / JSON inválido / tool o source fuera de allowlist → `LLMError` | `tests/unit/llm/test_gemini.py` | AC-P14-003 |
| Core y tenant no concatenados; `tool_results` → `functionResponse` | `tests/unit/llm/test_gemini.py` | AC-P14-004 |
| Isolation: el adaptador no pone `tenant_id` ni slug en el body | `tests/security/test_gemini_tenant_isolation.py` | AC-P14-010 |
| Hits del slug pedido; cero de otro slug | `tests/unit/knowledge/test_lab_search.py`, `tests/security/test_lab_knowledge_isolation.py` | AC-P14-005, AC-P14-010 |
| FAQ filtra mutaciones; vacío sigue vacío | `tests/unit/skills/test_faq.py` | AC-P14-006 |
| Compiler usa `enabled_tools` y `frozenset` de servidor | `tests/unit/agent/test_context_compiler.py` | AC-P14-007 |
| `build_runtime` elige Gemini o FakeLLM, Lab o Empty | `tests/unit/api/test_composition.py` | AC-P14-008, AC-P14-009 |

## Integración

Ningún test de esta fase llama a `generativelanguage.googleapis.com`. El transport se inyecta.

## Evidencia

Cada implementador pega el comando y el recorte PASS en su PR. Sin secreto real en el recorte.
