# TDD — Onboarding declarativo de tenants

**ID:** TDD-P08-001  
**Estado:** ready  
**Requisitos:** RF-038, RF-039, RF-043, RF-045, RNF-001, RNF-010, RNF-014, RNF-015

## Tenant package

```text
tenants/<slug>/
├── tenant.yaml
├── config.yaml
├── policies/
├── knowledge/manifest.yaml
├── integrations.yaml
└── evals.jsonl
```

Secret values y PDFs confidenciales no se versionan. Manifest referencia object sources/checksums autorizados. Schema version y config version son explícitos.

## Workflow de onboarding

```text
validate package
→ provision tenant disabled
→ configure channel/integrations references
→ ingest knowledge draft
→ run contract/security/evals preflight
→ publish config/knowledge
→ activate tenant under feature flag
→ smoke/canary
→ full activation or rollback
```

## CLI/application service

```python
class TenantOnboardingService(Protocol):
    async def validate(self, package: TenantPackage) -> ValidationReport: ...
    async def provision(self, package: TenantPackage, actor: Principal) -> Tenant: ...
    async def preflight(self, tenant: TenantContext) -> PreflightReport: ...
    async def activate(self, admin: TenantAdminContext) -> None: ...
    async def disable(self, admin: TenantAdminContext, reason: str) -> None: ...
```

Todos los comandos son idempotentes, auditados y requieren roles. `activate` exige preflight válido del mismo content/config hash.

## Preflight

- schema/config/policy validity;
- skills/tools/capabilities consistentes;
- secret references resolubles sin exponer values;
- channel mapping único;
- knowledge published y retrieval canario propio;
- no retrieval canario ajeno;
- MCP health/contract suite aplicable;
- eval smoke y workflow mock/sandbox;
- observability/run view;
- rollback inputs disponibles.

## Activación/desactivación

Activación cambia tenant a active y habilita channel mapping en transacción/control ordenado. Desactivación impide nuevos runs/jobs mutables, conserva auditoría, deja jobs pendientes en estado cancelado/paused según policy y no afecta otros tenants.

## Segundo tenant

Debe variar configuración, required fields, corpus, skills/tools y MCP target para probar que el diseño es realmente declarativo. Los fixtures pueden ser sintéticos; producción requiere dependencias del tenant real.

## Evidence diff

El informe compara commits antes/después. Cambios permitidos: tenant package, adapter/capability reutilizable, tests/config/docs. Cambios en Core se listan y justifican con ADR; una condición por slug falla el gate.
