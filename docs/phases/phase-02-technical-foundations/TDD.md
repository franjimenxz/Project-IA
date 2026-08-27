# TDD — Fundaciones técnicas

**ID:** TDD-P02-001  
**Estado:** ready  
**Requisitos:** RF-001–RF-008, RF-036–RF-037, RNF-001–RNF-003, RNF-008–RNF-015  
**ADRs:** ADR-001, ADR-002, ADR-004

## Arquitectura

El paquete `src/ia_mcp` separa `domain`, `application`, `ports` y `adapters` dentro de módulos orientados a capacidad. FastAPI es un adapter de entrada. SQLAlchemy/PostgreSQL y OpenTelemetry son adapters de salida. El dominio no importa esos frameworks.

## Estructura inicial

```text
src/ia_mcp/
├── api/app.py
├── api/errors.py
├── settings.py
├── tenancy/models.py
├── tenancy/ports.py
├── tenancy/service.py
├── tenancy/adapters/sqlalchemy.py
├── configuration/models.py
├── configuration/ports.py
├── configuration/service.py
├── configuration/adapters/sqlalchemy.py
├── persistence/base.py
├── observability/context.py
├── observability/audit.py
└── shared/errors.py
```

## Interfaces

```python
@dataclass(frozen=True, slots=True)
class TenantIdentity:
    tenant_id: UUID
    tenant_slug: str

@dataclass(frozen=True, slots=True)
class TenantAdminContext:
    identity: TenantIdentity
    principal_id: UUID
    roles: frozenset[str]
    correlation_id: UUID

@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: UUID
    tenant_slug: str
    config_version: int
    correlation_id: UUID

class TenantResolver(Protocol):
    async def resolve_channel(self, channel: str, account_id: str) -> TenantIdentity: ...

class ActiveConfigRepository(Protocol):
    async def get_active(self, identity: TenantIdentity) -> TenantConfig: ...

class ConfigurationService(Protocol):
    async def capture(self, identity: TenantIdentity, correlation_id: UUID) -> tuple[TenantContext, TenantConfig]: ...
    async def publish(self, admin: TenantAdminContext, draft: TenantConfigDraft) -> TenantConfig: ...
    async def activate(self, admin: TenantAdminContext, version: int) -> None: ...
```

## Config lifecycle

Draft valida schema y referencias → `validated` → publicación inmutable → activación atómica. `capture` lee config y versión en una operación consistente y construye el único `TenantContext` autorizado para el run. Rollback activa una versión publicada anterior y genera audit event.

## Persistencia

Primera migración crea `tenant`, `tenant_config`, `channel_integration` y `audit_event`. Las FK `(tenant_id, version)` y `(tenant_id, id)` impiden referencias cruzadas. Ningún repository público tenant-scoped acepta un UUID crudo: pre-captura usa `TenantIdentity`, administración usa `TenantAdminContext` y runtime usa `TenantContext`.

## API base

- `GET /health/live`: proceso vivo, sin dependencias.
- `GET /health/ready`: DB y configuración del proceso disponibles.
- `POST /v1/simulated/messages`: sólo test/development; verifica headers `X-Simulated-Account`, `X-Simulated-Timestamp` y `X-Simulated-Signature` (HMAC sobre timestamp + body), luego resuelve tenant y responde acknowledgment estructurado.

El body sólo contiene message/user/content. `channel_account_id` proviene del header autenticado, no acepta `tenant_id` ni account id del body, rechaza timestamps vencidos, firmas inválidas y replay, y no se registra en el router de producción.

## Errores

`DomainError(code, safe_message, retryable, details)` se transforma a Problem Details sin stack ni details sensibles. `TenantIsolationViolation` produce 404/403 según boundary, evento crítico y no revela recurso ajeno.

## Observabilidad

Middleware acepta/genera correlation id, crea span y lo propaga. Audit service recibe eventos tipados y redactor central. PII nunca se usa como atributo.

## Testing

SQLite no sustituye PostgreSQL para constraints o JSON/vector. Unit tests usan fakes; integration tests levantan PostgreSQL. Fixtures A/B cubren config y channel mapping. Clock y UUID factory son inyectables.

## Rollout

Esta fase no procesa pacientes reales. Feature flag mantiene endpoint simulado fuera de producción. Migraciones se prueban up/down en base efímera.
