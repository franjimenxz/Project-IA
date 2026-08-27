# P05-T01 — Intake de API

**Estado:** blocked por EXT-001–003  
**Objetivo:** producir mapping completo con fuente oficial por decisión.

No escribir adapter ni inferir ejemplos. Permitidos: mapping y manifest de fixtures sanitizadas. Escalar contradicciones y capabilities ausentes.

Gate de handoff: revisión institucional, arquitectura y seguridad; commit `docs: map institutional API capabilities`.

## Lectura obligatoria

Plan maestro §§24–25/30, contracts TDD, `../TDD.md`, acceptance/test plan, EXT-001–003 y ADR-003.

## Archivos e interfaces

Crear únicamente `../api-capability-mapping.md` y `fixtures-manifest.md`. No modificar código. Cada fila consume una operación oficial citada y produce decisión `supported|unsupported|compatible_extension|contract_conflict` con auth, schemas, errors, retry e idempotencia.

## Verificación y evidencia

Rojo documental: capability sin fuente/gap classification hace fallar review. Verde: todas las tools mapeadas y sign-off institucional/arquitectura/seguridad. Entregar hash/versión de fuente, AC-P05-001/002 y condición para desbloquear P05-T02.
