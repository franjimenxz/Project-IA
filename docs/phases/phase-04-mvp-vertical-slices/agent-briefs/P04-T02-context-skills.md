# P04-T02 — Skills y Context Compiler

**Estado:** ready · **Wave:** W3 · **Depends on:** P03-T03

Implementá Skill Protocol/Registry, routing autorizado y compilación mínima. Archivos permitidos: `skills/base.py`, `skills/registry.py`, `agent_runtime/context_*`, tests unit/security. No llamar LLM ni DB directamente.

Produce `ContextCompiler.compile(TenantContext, ContextRequest) -> CompiledContext`. Debe excluir secrets/config completa, limitar history/knowledge y emitir sólo tool schemas autorizados.

Criterios AC-P04-004–006, 014. Verificación `pytest tests/unit/agent tests/security/test_prompt_injection.py -v && mypy src/ia_mcp/agent_runtime src/ia_mcp/skills`. Commit `feat: compile minimal tenant context`.

