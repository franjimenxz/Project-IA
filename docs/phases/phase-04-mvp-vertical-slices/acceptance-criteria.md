# Criterios de aceptación — Fase 4

## Slice 4.1

| ID | Given / When / Then |
|---|---|
| AC-P04-001 | Dadas cuentas A/B, un mensaje de A resuelve A aunque el texto diga B |
| AC-P04-002 | Un external message repetido crea un solo Message y un solo efecto |
| AC-P04-003 | Un run captura config version y correlation id |
| AC-P04-004 | Skill deshabilitada no se selecciona ni expone tools |
| AC-P04-005 | Context Compiler incluye sólo políticas/campos pertinentes |
| AC-P04-006 | Credenciales y config completa no aparecen en CompiledContext |
| AC-P04-007 | Conversation/Session A no se recupera bajo TenantContext B |
| AC-P04-008 | Error de runtime queda auditado y produce respuesta segura |
| AC-P04-009 | PDF publicado de A se ingiere con source/page/version |
| AC-P04-010 | Documento draft/failed no participa de retrieval |
| AC-P04-011 | Search de A nunca devuelve chunk canario de B |
| AC-P04-012 | Respuesta FAQ cita sólo source IDs devueltos |
| AC-P04-013 | Evidencia insuficiente activa fallback configurado |
| AC-P04-014 | Prompt injection en PDF no habilita tool ni cambia tenant |
| AC-P04-015 | Endpoint simulado devuelve respuesta/outbox correlacionada |
| AC-P04-016 | Tenant suspendido falla antes de iniciar run |
| AC-P04-017 | Retrieval caído no produce afirmación institucional inventada |
| AC-P04-018 | Publicar nueva versión no cambia un run ya iniciado |
| AC-P04-019 | Dos tenants responden diferente usando corpus/config propios |

## Slice 4.2

| ID | Given / When / Then |
|---|---|
| AC-P04-020 | Solicitud inicia workflow `create_appointment` persistente |
| AC-P04-021 | Sólo se solicitan required_fields del tenant |
| AC-P04-022 | Datos inválidos no avanzan estado y reciben corrección segura |
| AC-P04-023 | Search usa contrato canónico y MCP del tenant |
| AC-P04-024 | Slots se presentan sin booking token/secrets |
| AC-P04-025 | Slot se revalida después de selección y antes de create |
| AC-P04-026 | Confirmación + replay crean exactamente un turno |
| AC-P04-027 | Timeout con estado incierto termina en manual review, no éxito |

## Slice 4.3

| ID | Given / When / Then |
|---|---|
| AC-P04-030 | Cancel requiere turno válido y confirmación |
| AC-P04-031 | Cancel replay devuelve mismo resultado sin segunda mutación |
| AC-P04-032 | Already cancelled se comunica como resultado idempotente |
| AC-P04-033 | Reschedule presenta y revalida nuevas opciones |
| AC-P04-034 | Slot perdido vuelve a opciones sin cancelar el turno original |
| AC-P04-035 | Estado parcial/ambiguo activa manual review |
| AC-P04-036 | Confirm pending cambia a confirmed una vez |
| AC-P04-037 | Already confirmed se trata como éxito idempotente |
| AC-P04-038 | Tenant A no puede mutar appointment B aunque conozca su ID |

## Slice 4.4

| ID | Given / When / Then |
|---|---|
| AC-P04-040 | Solicitud explícita crea handoff con reason tipado |
| AC-P04-041 | Resumen contiene datos recolectados y acciones, sanitizados |
| AC-P04-042 | Crear handoff y cambiar ownership es atómico |
| AC-P04-043 | Handoff replay no crea segundo caso |
| AC-P04-044 | `human_owned` impide mutaciones automáticas |
| AC-P04-045 | Provider caído conserva entrega pendiente durable |
| AC-P04-046 | Operador de A no recibe caso B |

## Slice 4.5

| ID | Given / When / Then |
|---|---|
| AC-P04-050 | Turno elegible programa reminder según timezone y 48h default |
| AC-P04-051 | Config distinta modifica anticipación sin código |
| AC-P04-052 | Confirmed/cancelled se omite antes de enviar |
| AC-P04-053 | Replay de job no duplica delivery |
| AC-P04-054 | Worker reiniciado retoma job pendiente |
| AC-P04-055 | Respuesta afirmativa continúa confirm workflow |
| AC-P04-056 | Error de canal reintenta según política y queda auditado |
| AC-P04-057 | Job A nunca usa canal, turno o config B |

