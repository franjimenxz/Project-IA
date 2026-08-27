# Fase 3 — Contratos internos

**Estado:** ready  
**Gate de entrada:** G1  
**Gate de salida:** G2

## Objetivo

Definir schemas canónicos, tools, errores y fakes ejecutables independientes de la API institucional.

## Entregables

- contratos comunes y de appointments;
- catálogo de tool names;
- versionado/compatibilidad;
- ToolResult/ToolError;
- registry y allowlist;
- fake MCP/agenda;
- contract suite reutilizable.

## Gate

Fake y cualquier adapter candidato pasan la misma suite; schemas tienen ejemplos y rechazan extra fields; ninguna credencial forma parte de un contrato expuesto al modelo.

