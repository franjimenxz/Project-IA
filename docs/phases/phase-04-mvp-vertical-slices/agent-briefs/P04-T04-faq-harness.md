# P04-T04 — FAQ Skill y Agent Harness

**Estado:** ready · **Wave:** W3 · **Depends on:** P04-T01–T03

Implementá ciclo de AgentRun, LLM Port/FakeLLM, FAQSkill y AnswerPolicy. No cablear endpoint ni proveedor real.

Produce `AgentHarness.handle_message(tenant, message) -> AgentTurnResult`. Toda respuesta informativa incluye source IDs válidos o kind `clarify|insufficient|handoff`.

Probar evidencia suficiente/insuficiente, error provider, source inventada, documento con injection y skill disabled. Criterios AC-P04-012–014, 017. Commit `feat: answer tenant FAQs with grounded evidence`.

## Lectura obligatoria

System TDD §§8–11, security TDD, `../TDD.md`, criterios y Task 4.

## Archivos exactos

Crear `src/ia_mcp/agent_runtime/harness.py`, `ports.py`, `models.py`, `src/ia_mcp/skills/faq.py`, `tests/unit/agent/test_harness.py`, `tests/unit/skills/test_faq.py`. No modificar HTTP route, SQL adapters o contratar LLM real.

## Interfaces y TDD

Consume repos de P04-T01, compiler P04-T02, KnowledgeService P04-T03 y `LLMPort.generate`. Produce `AgentHarness.handle_message(TenantContext, InboundMessage) -> AgentTurnResult`. Rojo: `test_faq_returns_insufficient_without_supported_hits`; verde: `pytest tests/unit/agent tests/unit/skills/test_faq.py tests/security/test_prompt_injection.py -v && mypy src/ia_mcp/agent_runtime`. Evidence report con trajectory/source assertions.
