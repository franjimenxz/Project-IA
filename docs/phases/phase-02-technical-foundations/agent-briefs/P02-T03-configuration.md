# P02-T03 — Configuración versionada

**Estado:** ready  
**Wave:** W1  
**Depends on:** P02-T02

## Lectura obligatoria

System TDD §§6–7, data model TenantConfig, ADR-002/004, `../TDD.md`, AC-P02-004–008/011 y Task 3.

## Archivos exactos

Crear `src/ia_mcp/configuration/models.py`, `ports.py`, `service.py`, `adapters/sqlalchemy.py`, `alembic/versions/0001_foundations.py` y `tests/integration/foundations/test_configuration.py`. No modificar channel/API.

Implementá modelos Pydantic, migraciones y repositorio SQL para capturar/publicar/activar/rollback. `capture(TenantIdentity, correlation_id)` construye `TenantContext`; administración usa `TenantAdminContext`. No aceptar UUID crudo, guardar secret values ni editar Channel API.

Constraints: PK `(tenant_id, version)`, publicación inmutable, content hash, activación atómica, actor auditado.

Pruebas PostgreSQL: v1/v2, snapshot, rollback, concurrent publish y tenant cruzado. Ejecutá `pytest -m integration tests/integration/foundations -v`.

Secuencia TDD: ejecutar primero el node de publicación inmutable/context capture para rojo; luego implementar schema/service/adapter y ejecutar integración, seguridad y mypy para verde.

Commit: `feat: version tenant configuration`.
