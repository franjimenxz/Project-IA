# Criterios de aceptación — Fase 14

| ID | Criterio |
|---|---|
| AC-P14-001 | `GeminiLLM.generate` con transport que responde `text` + `source_ids` ⊆ `allowed_source_ids` devuelve `LLMDecision` con esos valores. Sin red real |
| AC-P14-002 | El transport responde un `functionCall` cuyo nombre está en `tool_names`. `generate` devuelve `ToolCallProposal` con ese `name` y `arguments` parseados. Sin red real |
| AC-P14-003 | HTTP no-2xx, JSON inválido, `functionCall` fuera de `tool_names` o `source_ids` que no son subconjunto del allowlist → `generate` lanza `LLMError` con `code="provider_unavailable"`. El adaptador no reintenta |
| AC-P14-004 | El body enviado al transport tiene `systemInstruction` igual a `LLMRequest.instructions` (Core). `tone` y `tenant_instructions` viajan en partes distintas. Un test de aislamiento falla si el texto Core aparece concatenado con el de tenant. El body no incluye `tenant_id` ni slug |
| AC-P14-005 | `LabKnowledgeSearch.search` sobre un paquete `{packages_dir}/{slug}/knowledge/*.txt` devuelve hits del `TenantContext` pedido y cero hits de otro slug |
| AC-P14-006 | Con `enabled_tools` que incluye `appointments.search` y `appointments.create`, `FAQSkill.allowed_tools` contiene `appointments.search` y no contiene `appointments.create`. Con `enabled_tools` vacío sigue `frozenset()` |
| AC-P14-007 | `ContextCompiler.compile` con `enabled_tools={"appointments.search"}`, skill FAQ y catálogo servidor que incluye esa herramienta, pone `appointments.search` en los `tool_schemas`. El término tenant ya no se lee de `tenant_tools` |
| AC-P14-008 | `build_runtime` con `environ` que define `IA_MCP_SECRET_PLATFORM_LLM_GEMINI` construye `GeminiLLM`. El test no usa una clave real ni la escribe en disco |
| AC-P14-009 | `build_runtime` sin esa variable (o en blanco) construye `FakeLLM`. No lanza. No llama a Gemini. Sin `IA_MCP_TENANT_PACKAGES_DIR` el knowledge sigue siendo `EmptyKnowledgeSearch` |
| AC-P14-010 | Una búsqueda o un compile de tenant A no ve archivos ni `enabled_tools` de tenant B. El adaptador Gemini no ramifica por slug ni por `tenant_id` |

## Fuera de alcance

Mutaciones conversacionales, WhatsApp Cloud, embeddings, PDF, OCR, clave en git o HTML.
