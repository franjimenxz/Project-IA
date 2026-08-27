# {{PNN-TNN}} — {{nombre de tarea}}

**Estado:** draft  
**Wave:** {{WN}}  
**Plan:** {{ruta}}  
**Depends on:** {{IDs o “ninguna”}}

## Objetivo

{{un resultado único y observable}}

## Resultado demostrable

{{comando o escenario que prueba el resultado}}

## Lectura obligatoria

1. `docs/README.md`
2. `{{TDD}}`
3. `{{plan}}`
4. `{{contratos/ADR relevantes}}`

## Alcance

### Incluido

- {{cambio}}

### Excluido

- {{cambio y tarea owner}}

## Archivos

### Permitidos

- `{{path}}`

### Reservados/no modificar

- `{{path y owner}}`

## Interfaces

**Consume:**

```python
{{firma exacta}}
```

**Produce:**

```python
{{firma exacta}}
```

## Requisitos y criterios

| Requisito | Criterio |
|---|---|
| {{ID}} | {{AC-ID}} |

## Secuencia TDD

1. {{prueba roja exacta}}
2. {{comando y fallo esperado}}
3. {{implementación mínima}}
4. {{comando verde}}
5. {{suite relevante}}
6. {{controles estáticos}}

## Restricciones

- {{seguridad/multi-tenancy}}

## Evidencia requerida

- commit;
- comandos y resultados;
- criterios cubiertos;
- archivos modificados;
- decisiones/desviaciones;
- próxima tarea desbloqueada.

## Bloqueos

Usar el formato de `docs/00-governance/delegation-protocol.md`; no alterar contratos para evitar un bloqueo.

## Commit sugerido

```text
{{type: outcome}}
```

