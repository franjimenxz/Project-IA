# Criterios de aceptación — Fase 13

| ID | Criterio |
|---|---|
| AC-P13-001 | ADR-009 accepted; spec `2026-08-31-operator-html-pages-design.md` es la fuente de las páginas |
| AC-P13-002 | `write_lab_package` produce un package que `validate_package` acepta; replay de `provision` no duplica el slug |
| AC-P13-003 | `lab_enable` deja `capture()` posible; segunda llamada no duplica canales; ausente en production |
| AC-P13-004 | `GET /admin/instituciones` lista slugs visibles; el form solo admite campos del contrato actual |
| AC-P13-005 | POST de alta/edición escribe package, provisiona o publica, y llama `lab_enable` |
| AC-P13-006 | `GET`/`POST /admin/instituciones/{slug}/chat` llama al harness con el `TenantContext` de ese slug; no usa la firma del canal simulado |
| AC-P13-007 | El chat y la lista de A no revelan tenant B; 401 sin token; 404 para slug ajeno a un `tenant_admin` |
| AC-P13-008 | Cero secretos en HTML, fixtures o logs; cero `if tenant.slug` en Core; `FakeLLM` y activate productivo intactos |
