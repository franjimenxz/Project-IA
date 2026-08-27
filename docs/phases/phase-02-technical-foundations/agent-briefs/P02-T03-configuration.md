# P02-T03 — Configuración versionada

**Estado:** ready  
**Wave:** W1  
**Depends on:** P02-T02

Implementá modelos Pydantic, migraciones y repositorio SQL para publicar/activar/rollback. No guardar secret values ni editar Channel API.

Constraints: PK `(tenant_id, version)`, publicación inmutable, content hash, activación atómica, actor auditado.

Pruebas PostgreSQL: v1/v2, snapshot, rollback, concurrent publish y tenant cruzado. Ejecutá `pytest -m integration tests/integration/foundations -v`.

Commit: `feat: version tenant configuration`.

