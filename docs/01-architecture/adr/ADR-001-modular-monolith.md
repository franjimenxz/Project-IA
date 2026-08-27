# ADR-001 — Monolito modular con procesos separables

**Estado:** accepted  
**Fecha:** 2026-08-27

## Contexto

El MVP requiere API, runtime del agente, workflows, RAG, scheduler, handoff y MCP. Dividirlos desde el inicio en microservicios agregaría contratos de red, despliegues y consistencia distribuida antes de validar recorridos.

## Decisión

Implementar un repositorio y código base únicos con módulos de dominio separados. API, workers e MCPs se ejecutan como procesos distintos cuando lo requiere su operación, pero comparten contratos y paquetes versionados.

Los módulos se comunican mediante interfaces públicas. Dominio y application services no importan frameworks o adapters.

## Consecuencias positivas

- Menor complejidad de desarrollo y CI.
- Transacciones locales para workflows/outbox.
- Refactors de contratos durante la etapa temprana controlables.
- Extracción posterior posible por puertos existentes.

## Consecuencias negativas

- Requiere disciplina para evitar imports cruzados.
- Un repositorio grande puede aumentar acoplamiento si no se revisa ownership.
- Escala de despliegue menos granular hasta separar procesos/módulos.

## Alternativas descartadas

- Microservicio por componente: complejidad prematura.
- Aplicación sin módulos: impediría ownership y extracción.
- Funciones serverless por flujo: estado/workflows y observabilidad más fragmentados.

## Verificación

- dependency rules en CI;
- cada módulo tiene puertos y owner de datos;
- segundo tenant no modifica módulos compartidos;
- un adapter puede sustituirse sin cambiar dominio.

