# ADR-002 — TenantContext explícito y aislamiento en repositorios

**Estado:** accepted  
**Fecha:** 2026-08-27

## Contexto

Una fuga entre instituciones es un fallo crítico. Confiar sólo en filtros recordados por cada desarrollador o en un contexto global implícito es insuficiente.

## Decisión

Resolver tenant desde una identidad/cuenta autenticada antes de entrar al Agent Harness. Pasar un `TenantContext` inmutable y obligatorio a todos los servicios y repositorios sensibles. Usar claves/foreign keys compuestas e implementar defensa en profundidad en DB, vector store, object storage, caché, jobs y MCP.

Separar puertos administrativos cross-tenant de los puertos usados por runtime.

## Consecuencias positivas

- El compilador y type checker detectan omisiones.
- Tests pueden ejercer acceso cruzado en cada boundary.
- La autoridad del tenant no depende del prompt.
- Facilita auditoría consistente.

## Consecuencias negativas

- Firmas más verbosas.
- Migraciones e índices incluyen tenant.
- Operaciones administrativas requieren APIs separadas.

## Alternativas descartadas

- Context variable global: fácil de perder en jobs/async y difícil de auditar.
- Base de datos por tenant desde el MVP: operación y migraciones costosas; puede evaluarse para requisitos futuros.
- Filtro sólo en aplicación: defensa insuficiente.

## Verificación

- ninguna interfaz tenant-scoped acepta tenant opcional;
- suite negativa en todos los stores;
- prompt/header malicioso no cambia contexto;
- DB constraints impiden referencias cruzadas.

