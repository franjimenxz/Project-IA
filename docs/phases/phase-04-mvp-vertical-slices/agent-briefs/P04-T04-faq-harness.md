# P04-T04 — FAQ Skill y Agent Harness

**Estado:** ready · **Wave:** W3 · **Depends on:** P04-T01–T03

Implementá ciclo de AgentRun, LLM Port/FakeLLM, FAQSkill y AnswerPolicy. No cablear endpoint ni proveedor real.

Produce `AgentHarness.handle_message(tenant, message) -> AgentTurnResult`. Toda respuesta informativa incluye source IDs válidos o kind `clarify|insufficient|handoff`.

Probar evidencia suficiente/insuficiente, error provider, source inventada, documento con injection y skill disabled. Criterios AC-P04-012–014, 017. Commit `feat: answer tenant FAQs with grounded evidence`.

