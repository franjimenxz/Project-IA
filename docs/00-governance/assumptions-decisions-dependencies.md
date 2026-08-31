# Confirmaciones, decisiones y dependencias

**Estado:** ready

## Confirmado

| ID | Confirmación | Fuente |
|---|---|---|
| C-000 | Plan maestro normalizado por este paquete; SHA-256 `a13eb0dea1140a9c64c9ca5b8332bd1e9b7facfe527b682fb6c015f1ad779816` | Texto entregado el 2026-08-27 |
| C-001 | TDD significa Technical Design Document | Responsable del producto, 2026-08-27 |
| C-002 | El backend utiliza Python con FastAPI | Responsable del producto, 2026-08-27 |
| C-003 | El Core es multi-tenant y no contiene lógica institucional | Plan maestro |
| C-004 | MVP: appointments, FAQ y human handoff | Plan maestro |
| C-005 | El primer canal es WhatsApp, simulado hasta elegir proveedor | Plan maestro |
| C-006 | Knowledge Base inicial basada en PDFs | Plan maestro |
| C-007 | Integración médica mediante API REST y MCP institucional | Plan maestro |
| C-008 | El recordatorio inicial se configura a 48 horas | Plan maestro |
| C-009 | Deben coexistir al menos dos tenants | Definition of Done del plan maestro |

## Supuestos de diseño reversibles

| ID | Supuesto | Razón | Validación | Si resulta falso |
|---|---|---|---|---|
| A-001 | El MVP puede operar como monolito modular | Reduce complejidad sin perder boundaries | Carga y revisión en Fase 6 | Separar proceso mediante puertos existentes |
| A-002 | PostgreSQL cubre persistencia y pgvector cubre retrieval inicial | Consistencia operativa y menor superficie | Benchmark RAG y carga | Reemplazar KnowledgeRepository |
| A-003 | Redis puede usarse para cola/caché/locks, no como estado autoritativo | Coordinación distribuida | Resiliencia y operación | Sustituir adapter o cola |
| A-004 | Los documentos se almacenan en un backend S3-compatible | Interfaz estándar y portable | Spike de ingestión | Sustituir ObjectStore |
| A-005 | El canal simulado reproduce el envelope requerido por WhatsApp | Permite slices sin proveedor | Contract tests con proveedor elegido | Versionar ChannelMessage |

## Decisiones aceptadas

| ID | Decisión | Registro |
|---|---|---|
| D-001 | Monolito modular con procesos API/worker/MCP separables | ADR-001 |
| D-002 | TenantContext obligatorio y aislamiento en repositorios | ADR-002 |
| D-003 | Contratos canónicos y workflows determinísticos para mutaciones; MCPs institucionales no requieren implementar los seis tools Pydantic (amended ADR-005) | ADR-003, ADR-005 |
| D-004 | PostgreSQL autoritativo, Redis coordinador y pgvector reemplazable | ADR-004 |
| D-005 | MCP discovery (`tools/list`) e invocación genérica con intersección tenant/skill/servidor | ADR-005 |
| D-006 | Loop conversacional de tools de lectura; mutaciones siguen por workflow | ADR-006 |
| D-007 | Perfil de agente del tenant (`tone` + `instructions` opcionales) llega a cada `LLMRequest` sin concatenarse con Core | ADR-008 |

## Dependencias externas

Las dependencias `EXT-001` a `EXT-008` se administran en el catálogo de requisitos. Cada una tiene gate y condición de resolución. Ningún agente puede cambiar su estado sin evidencia adjunta.

## Decisiones que requieren ADR durante implementación

Estas decisiones tienen un momento de resolución definido y no bloquean la documentación actual:

| Tema | Momento | Criterio |
|---|---|---|
| Proveedor LLM inicial | Bootstrap de Slice 4.1 | Tool calling, observabilidad, región, costos y privacidad |
| Modelo de embeddings | Spike RAG de Slice 4.1 | Calidad en español, latencia, dimensión y costo |
| Librería de jobs | Diseño Slice 4.5 | Durabilidad, retries, scheduling y operación |
| Proveedor de secretos | Preparación de entorno real | Cloud elegido, rotación, auditoría y acceso local |
| Proveedor WhatsApp | Cuando `EXT-004` se satisfaga | Sandbox, webhooks, plantillas, costos y soporte |
| Plataforma de handoff | Cuando `EXT-005` se satisfaga | API, ownership, SLA y experiencia operativa |

## Regla de actualización

Una entrada cambia sólo mediante revisión documental. El cambio debe indicar motivo, impacto en requisitos, contratos, tareas, migraciones y pruebas.
