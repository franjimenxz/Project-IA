# TDD — Integración institucional real

**ID:** TDD-P05-001  
**Estado:** blocked por EXT-001–003  
**Requisitos:** RF-023–RF-027, RNF-002, RNF-004, RNF-010–RNF-015

## Arquitectura invariable

```text
Workflow → ToolExecutor → MCP Client → MCP institucional
                                      ↓
                              InstitutionalAdapter
                                      ↓
                                REST API oficial
```

El Core consume contratos de Fase 3. El adapter transforma requests/responses, clasifica errores y aplica autenticación. MCP Platform aporta tracing, audit, schemas, timeout policy, secret resolution y tool registry.

## Artefacto de intake

Al recibir documentación se crea `api-capability-mapping.md` con una fila por tool:

- operación oficial y versión;
- endpoint/method confirmados;
- auth/scopes;
- request fields y transformaciones;
- response fields y transformaciones;
- paginación/timezone;
- errores y retry semantics;
- idempotencia;
- rate limit/timeout;
- discrepancias con contrato canónico;
- evidencia de sandbox.

Ningún campo sin fuente puede entrar al adapter.

## Boundary del adapter

```python
class InstitutionalAppointmentAdapter(AppointmentCapability):
    def __init__(
        self,
        transport: InstitutionalTransport,
        secrets: SecretProvider,
        policy: IntegrationPolicy,
    ) -> None: ...
```

El transport recibe base URL allowlisted, auth resuelta y timeout. Las transformaciones son funciones puras y testeables. El adapter retorna sólo modelos canónicos.

## Autenticación

Se implementa únicamente el mecanismo documentado. Secret values se resuelven por `(tenant, integration, purpose)`, permanecen en memoria lo mínimo y se excluyen de repr/log/errors. La rotación no requiere cambiar config version si la reference permanece.

## Resiliencia

- timeout connect/read/write explícito;
- retries sólo para errores/operaciones documentadas como seguros;
- backoff con jitter y presupuesto total;
- rate limit respeta headers documentados;
- circuit policy si existe señal y operación segura;
- estado incierto en mutación termina `manual_review_required`;
- idempotency usa mecanismo oficial o dedupe local claramente limitado.

## Compatibilidad

Si la API no puede satisfacer un contrato, se documentan alternativas: reducir capability del tenant, extender contrato de forma genérica compatible o crear versión nueva. Nunca se agrega `if tenant == instituto` al Core.

## Seguridad

Hosts allowlisted, TLS verificado, payload size limitado, redirects deshabilitados salvo documentación, responses validadas, PII minimizada y summaries auditables sanitizados.

## Rollout

Feature flag por tenant: shadow/read-only donde sea posible → canary interno → operaciones no mutables → mutaciones controladas → activación. Rollback vuelve a fake/disabled sólo en entornos donde sea seguro y no afirma mutaciones no reconciliadas.

