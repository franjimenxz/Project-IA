# Protocolo de delegación a agentes

**Estado:** ready

## Objetivo

Permitir trabajo concurrente sin pérdida de contexto, contratos incompatibles ni cierres sin evidencia.

## Cuándo una tarea está lista

Una tarea puede delegarse sólo si:

- su brief está documentalmente `ready` y el tablero de delegación marca su ejecución `ready`;
- sus dependencias están `accepted`;
- el TDD y los criterios asociados están aprobados;
- las interfaces consumidas existen o tienen fake versionado;
- los archivos permitidos no están reservados por otra tarea;
- los comandos de prueba son concretos;
- no depende de una `EXT` sin satisfacer.

El estado documental del brief indica que las instrucciones son completas. El estado operativo vive en `delegation-board.md` y controla si la tarea puede ejecutarse ahora.

## Paquete obligatorio del agente

El prompt de delegación debe incluir la ruta al brief y ordenar la lectura de:

1. `docs/README.md`;
2. requisitos y ADRs citados por el brief;
3. TDD de fase;
4. plan de implementación;
5. brief específico;
6. archivos e interfaces existentes relacionados.

El agente no necesita leer documentación no referenciada salvo que encuentre una contradicción.

## Boundary de tarea

El brief declara:

- archivos que puede crear/modificar;
- interfaces que consume y produce;
- cambios expresamente excluidos;
- requisitos y criterios cubiertos;
- evidencia esperada.

Cambiar un contrato compartido, migración previa, ADR o archivo reservado requiere aprobación del coordinador.

## Ciclo de ejecución

```text
Brief aceptado
→ inspección local
→ prueba roja
→ implementación mínima
→ prueba verde
→ refactor
→ suite relevante
→ controles estáticos
→ auto-revisión
→ commit
→ handoff con evidencia
```

## Formato de bloqueo

```markdown
Estado: blocked
Causa: <hecho verificable>
Impacto: <criterios/tareas afectados>
Intentos realizados: <comandos y resultados>
Decisión o dato requerido: <pregunta única y concreta>
Opciones seguras: <alternativas y trade-offs>
Condición de desbloqueo: <evidencia necesaria>
```

Un agente no marca bloqueo por complejidad o tiempo; primero agota verificaciones y alternativas dentro del scope.

## Formato de handoff

```markdown
Tarea: PNN-TNN
Estado: in_review
Resultado: <comportamiento entregado>
Commit: <hash>
Archivos: <rutas>
Pruebas: <comandos y resumen>
Criterios: <IDs satisfechos>
Decisiones: <ninguna o referencias ADR>
Desviaciones: <ninguna o detalle>
Riesgos residuales: <ninguno o detalle>
Próxima tarea desbloqueada: <ID>
```

## Revisión de dos etapas

### Revisión 1 — Conformidad

Comprueba alcance, requisitos, criterios, contratos y ausencia de cambios no autorizados.

### Revisión 2 — Calidad

Comprueba diseño, seguridad, aislamiento, legibilidad, pruebas, tipos, errores, observabilidad y mantenibilidad.

Una corrección vuelve al mismo agente con hallazgos exactos. No se reasigna salvo indisponibilidad o cambio de ownership explícito.

## Paralelización

- Un único owner por interfaz y archivo durante una wave.
- Contratos se aceptan antes de delegar consumidores.
- Cada agente implementa una tarea revisable, no una fase completa.
- La integración se ejecuta al cerrar cada wave.
- Las tareas de documentación pueden correr en paralelo con adapters sólo cuando no cambian contratos.

## Política Git

- Rama principal protegida cuando exista remoto.
- Una rama o worktree por tarea de implementación.
- Commits pequeños con prefijo `feat`, `fix`, `test`, `docs`, `refactor`, `chore` o `ci`.
- No reescribir trabajo ajeno.
- No mezclar refactors no relacionados.
- Cada commit debe pasar las pruebas declaradas por la tarea.

## Prompt mínimo de delegación

```text
Implementá la tarea PNN-TNN siguiendo el brief <ruta absoluta o relativa>.
Leé todos los documentos marcados como obligatorios en el brief.
Respetá archivos permitidos, interfaces y exclusiones.
Aplicá prueba roja, implementación mínima, prueba verde y suite relevante.
No cambies contratos o ADRs sin escalar.
Entregá el handoff en el formato definido por delegation-protocol.md.
```
