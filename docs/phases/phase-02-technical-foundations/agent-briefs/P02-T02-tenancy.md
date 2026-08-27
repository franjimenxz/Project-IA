# P02-T02 — TenantContext y resolver

**Estado:** ready  
**Wave:** W1  
**Depends on:** P02-T01

Implementá modelos frozen y resolución exclusivamente por channel/account. Permitidos: `tenancy/*` y tests unitarios. No implementar SQL ni aceptar tenant desde mensaje/header público.

Produce `TenantIdentity`, `TenantContext`, `ChannelIntegrationRepository` y `TenantService.resolve(channel, account_id)`.

Pruebas: account A, desconocida, disabled, texto spoofing e inmutabilidad. Comando `pytest tests/unit/tenancy -v && mypy src/ia_mcp/tenancy`.

Commit: `feat: resolve tenant from channel identity`.

