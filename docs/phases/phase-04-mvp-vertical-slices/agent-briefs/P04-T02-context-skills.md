# P04-T02 — Skills y Context Compiler

**Estado:** ready · **Wave:** W3 · **Depends on:** P03-T03

Implementá Skill Protocol/Registry, routing autorizado y compilación mínima. Archivos permitidos: `skills/base.py`, `skills/registry.py`, `agent_runtime/context_*`, tests unit/security. No llamar LLM ni DB directamente.

Produce `ContextCompiler.compile(TenantContext, ContextRequest) -> CompiledContext`. Debe excluir secrets/config completa, limitar history/knowledge y emitir sólo tool schemas autorizados.

Criterios AC-P04-004–006, 014. Verificación `pytest tests/unit/agent tests/security/test_prompt_injection.py -v && mypy src/ia_mcp/agent_runtime src/ia_mcp/skills`. Commit `feat: compile minimal tenant context`.

## Lectura obligatoria

System TDD §§8–10, ADR-002, security TDD, `../TDD.md`, criterios y Task 2 del plan.

## Archivos exactos

Crear `src/ia_mcp/skills/base.py`, `skills/registry.py`, `agent_runtime/context_models.py`, `context_compiler.py`, `tests/unit/agent/test_context_compiler.py` y `tests/unit/skills/test_registry.py`. No modificar ToolExecutor, knowledge adapter ni LLM provider.

## Interfaces y TDD

Consume `TenantContext`, `TenantConfig`, Skill y ToolRegistry; produce `ContextCompiler.compile(TenantContext, ContextRequest) -> CompiledContext`. Rojo: node `test_compiler_excludes_disabled_tools`; verde: comando ya indicado. Evidencia: serialized context sin secret/config completa y AC-P04-004–006/014.
