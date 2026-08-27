# Architecture Decision Records

Los ADRs registran decisiones que afectan múltiples fases o interfaces. Son inmutables una vez aceptados; un cambio crea un ADR nuevo que marca al anterior como `superseded`.

| ADR | Decisión | Estado |
|---|---|---|
| [ADR-001](ADR-001-modular-monolith.md) | Monolito modular y procesos separables | accepted |
| [ADR-002](ADR-002-tenant-context-and-isolation.md) | TenantContext explícito y repositorios aislados | accepted |
| [ADR-003](ADR-003-canonical-contracts-and-workflows.md) | Contratos canónicos y workflows determinísticos | accepted |
| [ADR-004](ADR-004-storage-and-async-foundation.md) | PostgreSQL autoritativo, pgvector y Redis coordinador | accepted |

Cada ADR incluye contexto, decisión, consecuencias, alternativas y verificación.

