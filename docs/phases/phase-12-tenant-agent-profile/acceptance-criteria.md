# Criterios de aceptación — Fase 12

| ID | Criterio |
|---|---|
| AC-P12-001 | ADR-008 propuesto y fase 12 documentada (TDD, criterios, plan, test plan, brief de T02); ADR-002, ADR-006 y ADR-007 sin enmienda |
| AC-P12-002 | `AgentConfig` declara `instructions: str \| None` con máximo 2000 caracteres; `None` y `""` equivalen a ausente; `tone` sigue obligatorio; `extra="forbid"` rechaza `persona`, `system_prompt` y cualquier campo no declarado |
| AC-P12-003 | `LLMRequest` declara `tone: str = ""` y `tenant_instructions: str \| None = None`; un constructor que no los pasa sigue siendo válido; `FakeLLM` sigue compilando sin leerlos; `AnswerKind` no cambia |
| AC-P12-004 | `compile` deja `core_instructions` igual a `CORE_INSTRUCTIONS`; `policies["agent"]` incluye `tone` y, si hay texto, `instructions`; el texto del tenant no aparece concatenado en `core_instructions` |
| AC-P12-005 | Cada `generate` del turno recibe el `tone` y las `tenant_instructions` del `AgentConfig` capturado para ese `TenantContext`; `LLMRequest.instructions` es exactamente `CORE_INSTRUCTIONS` |
| AC-P12-006 | El schema de package admite `agent.instructions` opcional (`maxLength` 2000); un package sin la clave sigue válido; `PackageConfig.agent` es `AgentConfig`; no existe un tipo paralelo |
| AC-P12-007 | El `LLMRequest` de tenant B no contiene el `tone` ni las `instructions` de A; todo boundary del camino recibe `TenantContext`; la `config_version` del turno no se cambia a mitad del run |
| AC-P12-008 | Cero condiciones por nombre o slug de institución en compiler y harness; knowledge no aporta personalidad; fixtures y docs sin secretos; el workflow engine no se invoca; la suite FAQ existente pasa sin cambio de expectativa |
