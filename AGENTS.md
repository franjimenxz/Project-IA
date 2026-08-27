# Instrucciones para agentes

## Antes de cambiar archivos

1. Leer `docs/README.md`.
2. Confirmar que la tarea está `ready` en `docs/00-governance/delegation-board.md`.
3. Leer el brief, TDD, ADRs, criterios y plan citados.
4. Verificar dependencias y archivos permitidos.
5. Inspeccionar el estado actual; no asumir que el plan refleja código ya implementado.

## Reglas obligatorias

- No inventar API, credenciales, autenticación, requisitos legales ni campos institucionales.
- `TenantContext` es obligatorio en todo boundary tenant-scoped.
- No agregar condiciones por nombre/slug de institución dentro del Core.
- No pasar secretos al LLM, logs, traces, fixtures o repositorio.
- Toda mutación crítica pasa por workflow e idempotencia.
- Aplicar test-first: prueba roja por la razón esperada, implementación mínima, verde, refactor y suite relevante.
- Respetar interfaces y archivos del brief; escalar cambios compartidos.
- No editar trabajo no relacionado ni sobrescribir cambios ajenos.
- Mantener trazabilidad y entregar evidencia reproducible.

## Handoff

Usar el formato de `docs/00-governance/delegation-protocol.md`. El coordinador, no el implementador, actualiza el estado de la tarea después de las dos revisiones.

