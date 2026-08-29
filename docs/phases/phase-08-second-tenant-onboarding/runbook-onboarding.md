# Runbook — Onboarding y rollback del segundo tenant

**Estado:** ready  
**Changeset registrado:** `dd810e0..11b3de5` (padre real del commit de onboarding tras el rebase de P08-T04)

Este procedimiento incorpora un tenant sintético B sin cambiar Core. Los valores de secreto no se versionan: sólo referencias `sm://`.

## Precondiciones

- Package declarativo bajo `tenants/fixtures/tenant-b/` (config, corpus, tools y MCP distintos de A).
- Principal `platform_admin` por `--principal-id` y `--role`. No hay autenticación federada.
- PostgreSQL local; las suites leen la misma URL vía `IA_MCP_TEST_DATABASE_URL` (`tests/fixtures/database.py`).
- `DATABASE_URL` exportada; el CLI construye `TenantOnboardingService` con ese engine.
- Corpus canario B en `tenants/fixtures/tenant-b/knowledge/hours-b.txt` (`canary-tenant-b`).

```text
export DATABASE_URL=postgresql+psycopg://<usuario>@<host>:5432/<base>
```

## Activación

```text
python -m ia_mcp.onboarding validate tenants/fixtures/tenant-b
python -m ia_mcp.onboarding provision tenants/fixtures/tenant-b \
  --principal-id <platform-admin-uuid> --role platform_admin
```

Ingerir y publicar el documento canario B con `KnowledgeService` (payload = `hours-b.txt`, checksum del manifest). El ingest usa `TenantContext` de B.

```text
python -m ia_mcp.onboarding preflight tenants/fixtures/tenant-b \
  --principal-id <platform-admin-uuid> --role platform_admin
python -m ia_mcp.onboarding activate tenant-b \
  --report-hash <preflight-report-hash> \
  --principal-id <platform-admin-uuid> --role platform_admin
```

`activate` exige el hash del reporte passing del mismo content/config hash. Un hash obsoleto o un check fallido no activa.

## Verificación A/B

- Retrieval de B devuelve `canary-tenant-b` y nunca `canary-tenant-a`.
- MCP/tools de B salen de `integrations.yaml` / `config.yaml` (`fake-appointments-b`, search/get/create). A permanece en `fake-appointments-a` y el set completo de tools.
- Runs, jobs y config de A no cambian.

```text
python scripts/check_tenant_specific_core.py --base dd810e0 --head 11b3de5
```

El script falla si Core introduce un `if tenant_slug == "..."` / nombre de institución, o si el changeset toca Core fuera de adapters.

## Disable / rollback

```text
python -m ia_mcp.onboarding disable tenant-b \
  --principal-id <platform-admin-uuid> --role platform_admin \
  --reason cutover-hold
```

B queda `disabled`: no acepta jobs/runs mutables nuevos. La auditoría se conserva. A sigue `active` con sus jobs y runs.

## Secretos y aislamiento

- Sólo URIs `sm://` en package, logs y reportes.
- Todo boundary tenant-scoped recibe `TenantContext`.
- No hay condiciones por slug o nombre de institución en Core.
