# P02-T02 — TenantContext y resolver

**Estado:** ready  
**Wave:** W1  
**Depends on:** P02-T01

## Lectura obligatoria

System TDD §§5–7, ADR-002, security TDD, `../TDD.md`, criterios AC-P02-002/003/011 y Task 2.

## Archivos exactos

Crear `src/ia_mcp/tenancy/models.py`, `ports.py`, `service.py` y `tests/unit/tenancy/test_service.py`. No implementar SQL, config capture o API.

Implementá modelos frozen y resolución exclusivamente por channel/account. Permitidos: `tenancy/*` y tests unitarios. No implementar SQL ni aceptar tenant desde mensaje/header público.

Produce `TenantIdentity`, el tipo `TenantContext` sin factory pública, `ChannelIntegrationRepository` y `TenantService.resolve(channel, account_id)`. Configuration Service de P02-T03 es el único constructor de contexto post-config.

Pruebas: account A, desconocida, disabled, texto spoofing e inmutabilidad. Comando `pytest tests/unit/tenancy -v && mypy src/ia_mcp/tenancy`.

Commit: `feat: resolve tenant from channel identity`.
