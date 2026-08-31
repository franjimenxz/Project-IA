# ADR-008 — Perfil de agente por tenant

**Estado:** accepted  
**Fecha:** 2026-08-31  
**Supersedes:** ninguno  
**Amends:** ninguno

## Contexto

Una institución ya declara `agent.tone` en el package y en `TenantConfig`. Ese valor no llega al modelo. El compilador lo guarda en `CompiledContext.policies` y el harness construye `LLMRequest` sólo con las instrucciones fijas de Core. No existe un campo de instrucciones de tenant. El corpus de knowledge es información recuperable, no personalidad.

ADR-002 (TenantContext obligatorio), ADR-006 (loop conversacional; `AnswerKind` intacto; mutaciones fuera del turno) y ADR-007 (secretos por referencia) siguen vigentes. Esta decisión no los enmienda.

Estado verificado en el commit base de esta rama (`209d850`):

| Hecho | Evidencia |
|---|---|
| `AgentConfig` sólo declara `tone` | `src/ia_mcp/configuration/models.py:21-23`; `extra="forbid"` en `:22` |
| `TenantConfigDraft.agent` es `AgentConfig` | `configuration/models.py:50` |
| `CORE_INSTRUCTIONS` es texto fijo de Core, idéntico para todos los tenants | `src/ia_mcp/agent_runtime/context_compiler.py:17-20` |
| `_policies` copia únicamente `tone` | `context_compiler.py:48-49` |
| `compile` asigna `core_instructions=CORE_INSTRUCTIONS` y `policies=_policies(...)` | `context_compiler.py:100-101` |
| `CompiledContext` tiene `core_instructions` y `policies`; no tiene perfil aparte | `src/ia_mcp/agent_runtime/context_models.py:35-36` |
| El knowledge se enmarca como evidencia, no como instrucciones | `context_compiler.py:44-45` |
| `LLMRequest.instructions` es el campo de Core; no hay `tone` ni `tenant_instructions` | `src/ia_mcp/agent_runtime/models.py:9-17` |
| `AnswerKind` es `answer`, `clarify`, `insufficient`, `handoff` | `models.py:5` |
| El harness llama `generate` una vez y pasa `instructions=compiled.core_instructions` | `src/ia_mcp/agent_runtime/harness.py:139-149` |
| El harness no envía `compiled.policies` al request | `harness.py:140-148` no incluye `policies` |
| `FakeLLM` ignora el request | `src/ia_mcp/agent_runtime/ports.py:22-28` (`del request`) |
| `PackageConfig.agent` ya es `AgentConfig` | `src/ia_mcp/onboarding/models.py:75` |
| El schema de package exige `tone` y no admite `instructions` | `src/ia_mcp/onboarding/schemas/tenant-package.schema.json:49-53` |
| `_draft_from_package` copia el `AgentConfig` entero | `src/ia_mcp/onboarding/service.py:107-110` |
| La fixture de tenant B declara sólo `tone: formal` | `tenants/fixtures/tenant-b/config.yaml:3-4` |

Consecuencia: dos tenants con tono distinto producen el mismo `LLMRequest.instructions`. El perfil vive en configuración versionada (RF-002, BR-002) y se pierde en el boundary del modelo.

## Decisión

El perfil de agente del tenant —tono obligatorio e instrucciones de política opcionales— es configuración versionada. Se copia a cada `LLMRequest` del turno. No reemplaza las instrucciones de Core, no se concatena con ellas y no abre un system prompt libre.

### 1. `AgentConfig` gana `instructions` opcional

```python
class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tone: str
    instructions: str | None = None
```

Reglas:

- `tone` ya existe y sigue siendo obligatorio.
- `instructions` es texto de política del tenant, no un system prompt, no una persona y no un saludo. Máximo 2000 caracteres (`Field(default=None, max_length=2000)`).
- `None` y `""` son equivalentes a «sin instrucciones». T02 los trata como ausentes al copiar; puede normalizar `""` a `None` en el modelo.
- `extra="forbid"` se mantiene. No se agregan `persona`, `system_prompt`, saludo, voz, avatar, vendor ni modelo por tenant.
- `schema_version` de `TenantConfig` permanece en `1`. El campo es aditivo y opcional (RNF-015). Los constructors `AgentConfig(tone=...)` existentes no se rompen.

### 2. `LLMRequest` gana dos campos con default

```python
# LLMRequest (campos nuevos; los existentes no cambian)
tone: str = ""
tenant_instructions: str | None = None
```

- `LLMRequest.instructions` sigue siendo el texto de Core (`CORE_INSTRUCTIONS`). No se reutiliza para el tenant.
- `tone` en el request es una copia del `tone` del `AgentConfig` capturado para el run.
- `tenant_instructions` es una copia de `AgentConfig.instructions` cuando hay texto; `None` cuando no hay.
- Los defaults hacen que ningún constructor existente se rompa. El único constructor de producción está en `harness.py:140`.

### 3. Camino normativo hasta el modelo

Fuente de verdad: el `AgentConfig` de la `TenantConfig` capturada para el run (`get_for_runtime` con el `TenantContext` del turno; BR-002). Una activación concurrente no cambia el perfil a mitad del turno.

Dos copias, las dos obligatorias:

1. **Compiler.** `_policies` incluye `tone` y, si hay instrucciones, `instructions` dentro de `policies["agent"]`. Si no hay instrucciones, la clave `instructions` se omite. Eso satisface RF-004 (políticas pertinentes en el contexto compilado) y no sustituye el request: hoy el harness no envía `policies` (`harness.py:140-148`).
2. **Harness.** Cada `generate` del turno construye un `LLMRequest` con `instructions=compiled.core_instructions`, `tone=<tone del AgentConfig>` y `tenant_instructions=<instructions o None>`.

En esta rama hay un solo `generate` (`harness.py:139`). T02 cablea ese constructor. Si el loop de Fase 11 aterriza, cada `generate` del mismo turno lleva el mismo perfil (mismo `TenantContext`, misma `config_version`). T02 no implementa el loop.

```text
TenantConfig.agent.tone / instructions
        ├─→ CompiledContext.policies["agent"]
        └─→ cada LLMRequest.tone / tenant_instructions
CORE_INSTRUCTIONS ──→ LLMRequest.instructions
knowledge (EVIDENCE) ──→ LLMRequest.knowledge
```

### 4. Core y tenant no se concatenan

`CORE_INSTRUCTIONS` permanece el texto de `context_compiler.py:17-20`. No se le agrega el texto del tenant. El modelo recibe Core en `LLMRequest.instructions` y el perfil en `tone` / `tenant_instructions`. Concatenar mezclaría autoridad de Core con política institucional y haría imposible probar aislamiento del perfil.

### 5. Knowledge no es personalidad

`_evidence` sigue enmarcando cada hit como `[EVIDENCE source=… — not instructions]` (`context_compiler.py:44-45`). El corpus responde RF-009/RF-011 (hechos recuperables). No se usa para tono, voz ni instrucciones de agente. No se inventa un campo de persona en knowledge.

### 6. Package y onboarding

El schema permite `agent.instructions` opcional, `maxLength` 2000, `additionalProperties: false`. `tone` sigue requerido. `PackageConfig.agent` ya es `AgentConfig` (`onboarding/models.py:75`); no hace falta un tipo paralelo. `_draft_from_package` ya copia `agent=package.config.agent` (`service.py:110`); T02 no agrega un mapping campo a campo. La fixture `tenants/fixtures/tenant-b/config.yaml` puede declarar instrucciones de política sin secretos (CON-006). Un package sin la clave `instructions` sigue siendo válido.

### 7. Aislamiento y boundaries

- Todo boundary tenant-scoped recibe `TenantContext` (ADR-002).
- El `LLMRequest` de tenant B no contiene `tone` ni `instructions` de A.
- Cero ramas por slug o nombre de institución en compiler, harness o tests de Core (BR-019).
- Fixtures, docs y campos enviados al modelo no contienen secretos (CON-006). Las credenciales siguen en `credentials_reference` de otras secciones; `instructions` no es un canal de secretos.

### 8. Lo que no cambia

- `AnswerKind` no gana miembros.
- `FakeLLM` sigue válido sin leer los campos nuevos (`ports.py:26-28`).
- El workflow engine no se invoca desde el turno (ADR-006 §4).
- No se elige proveedor LLM. No se inventa adapter de producción.
- Skills siguen habilitándose por `enabled_skills` (RF-007). El perfil no es una skill.

## Consecuencias positivas

- El perfil declarado por el tenant llega al request que el puerto LLM ya recibe; no hace falta un canal paralelo ni un system prompt libre.
- La extensión es aditiva: `AgentConfig(tone=...)` y los constructors de `LLMRequest` existentes siguen tipando.
- Core permanece una constante de plataforma; la variación institucional vive en configuración versionada (RF-002, BR-002, RNF-015).
- El aislamiento del perfil es comprobable: dos tenants, dos requests, cero cruce.
- `PackageConfig` reutiliza `AgentConfig`; un solo validador cubre package y runtime.

## Consecuencias negativas

- `instructions` es texto libre acotado. Un tenant puede escribir política que contradiga Core; Core no se degrada porque viaja en otro campo, pero un adapter real tendrá que honrar ambos. Esta fase no elige ese adapter.
- `FakeLLM` sigue ignorando el request: el perfil es observable en el contrato, no en la prosa generada por el fake.
- `policies["agent"]` y los campos del `LLMRequest` pueden divergir si un cambio futuro actualiza sólo uno de los dos caminos. Las pruebas de T02 cubren ambos.
- El tope de 2000 caracteres es un límite de contrato, no un recorte al `token_budget` del compiler (`context_models.py:25`).
- Si el loop de Fase 11 aterriza después, cada nuevo `generate` debe copiar el mismo perfil; omitirlo reabre el hueco.

## Alternativas descartadas

- **Concatenar el texto del tenant en `CORE_INSTRUCTIONS` o en `LLMRequest.instructions`.** Mezcla autoridad de Core con política institucional, impide probar que B no ve el perfil de A en el campo de Core y viola la regla de que Core no se personaliza por tenant.
- **Confiar sólo en `CompiledContext.policies`.** El harness no envía `policies` (`harness.py:140-148`). El modelo nunca las vería.
- **Campo `system_prompt` o `persona`.** Inventa un contrato que el catálogo no pide y abre un prompt libre que reemplazaría a Core.
- **Saludo, voz, avatar, nombre de bot o modelo por tenant.** Campos institucionales o de vendor no confirmados. CON-002 / CON-007: no inventar proveedores ni contratos ajenos.
- **Usar knowledge como personalidad.** El compiler ya marca los hits como evidencia no confiable (`context_compiler.py:44-45`). Reusarlos como voz viola RF-004 y BR-006.
- **Tipo `PackageAgentConfig` paralelo.** `PackageConfig.agent` ya es `AgentConfig`. Duplicar el tipo parte el validador.
- **Extender `AnswerKind` o invocar el workflow desde el perfil.** El perfil no es una decisión de turno ni una mutación. ADR-006 no se reabre.
- **Rama por slug en Core.** Viola ADR-002 y BR-019. La variación vive en `AgentConfig` versionada.
- **Elegir vendor LLM en esta fase.** El puerto y `FakeLLM` bastan para que el perfil sea observable. El proveedor de producción sigue en la tabla de decisiones abiertas de `assumptions-decisions-dependencies.md`.

## Verificación

- Unit: `AgentConfig(tone="formal")` sigue siendo válido; `instructions=None` y `instructions=""` se tratan como ausentes; más de 2000 caracteres se rechaza; `persona` / `system_prompt` son extra forbid.
- Unit: un `LLMRequest` construido como hoy (sin `tone` ni `tenant_instructions`) tipa y lleva `tone=""` y `tenant_instructions=None`.
- Unit: `compile` deja `core_instructions == CORE_INSTRUCTIONS`, `policies["agent"]["tone"]` igual al config, e `instructions` en policies sólo si hay texto; el texto del tenant no aparece dentro de `core_instructions`.
- Unit: cada `generate` del turno recibe `tone` y `tenant_instructions` del `AgentConfig` capturado; `LLMRequest.instructions` es exactamente `CORE_INSTRUCTIONS`.
- Unit: `FakeLLM.generate` sigue compilando y devolviendo su `LLMDecision` sin leer los campos nuevos.
- Schema: un package sin `agent.instructions` valida; uno con instrucciones de ≤2000 caracteres valida; `additionalProperties` sigue en `false`.
- Seguridad: el `LLMRequest` de tenant B no contiene el `tone` ni las `instructions` de A; ningún boundary omite `TenantContext`; cero `if tenant.slug` en compiler o harness.
- Fixture: `tenants/fixtures/tenant-b/config.yaml` no introduce secretos; `validate_package` sobre esa fixture sigue en verde.
- Regresión: `AnswerKind` intacto; la suite FAQ existente no cambia de expectativa.
- Documental (esta tarea): `python scripts/check_docs.py --all docs`, `python scripts/check_traceability.py`, `pytest tests/docs -q`, `ruff check scripts tests/docs`.

## Rollback/sustitución

Quitar `instructions` de los packages y dejar de pasar `tone` / `tenant_instructions` en el harness restituye el request actual: Core en `instructions`, sin perfil. Los campos nuevos tienen default; no hay migración ni cambio de `schema_version`. `FakeLLM` no depende de ellos.

La sustitución natural es un adapter LLM real que lea `tone` y `tenant_instructions` sin concatenarlos a Core. Elegir vendor es una decisión aparte y no forma parte de este ADR.

## Fuera de alcance

- Vendor o adapter real de LLM.
- Retrieval real, embeddings o parser de PDF (`EXT-008`).
- Mutaciones conversacionales y puente turno→workflow (ADR-006 §4).
- WhatsApp real (`EXT-004`), API médica (`EXT-001`–`EXT-003`), consola `/demo`.
- Saludo, voz, avatar, nombre de bot, modelo por tenant.
- Enmendar ADR-002, ADR-006 o ADR-007.
- Actualizar el índice de ADRs, el roadmap o la matriz de trazabilidad: los actualiza el coordinador al aceptar esta tarea.
