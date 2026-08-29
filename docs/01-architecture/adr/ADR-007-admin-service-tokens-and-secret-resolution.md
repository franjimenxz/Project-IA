# ADR-007 — Tokens de servicio administrativos y resolución de secretos

**Estado:** proposed  
**Fecha:** 2026-08-29  
**Supersedes:** ninguno  
**Amends:** ninguno

## Contexto

El plano administrativo está montado y es inalcanzable, y las credenciales que la configuración referencia no las resuelve nadie. Las dos cosas son una sola: el mecanismo de autenticación elegido valida un token guardado como secreto, así que sin resolución de secretos no hay autenticación.

Estado verificado en `main` (`02c7e12`):

| Hecho | Evidencia |
|---|---|
| La identidad administrativa es estado de proceso, no de request | `src/ia_mcp/api/auth/admin.py:15` y `src/ia_mcp/onboarding/api.py:291`, ambos `getattr(request.app.state, "principal", None)` |
| Nada la fija en un proceso real | ningún archivo de `src/` escribe `app.state.principal`; sólo lo hacían cuatro suites de test |
| Los 8 endpoints administrativos responden 401 siempre | `src/ia_mcp/api/app.py:33-34` monta ambos routers: runs (`src/ia_mcp/api/routes/admin_runs.py:37`, `:61`, JSON y HTML) y onboarding (`src/ia_mcp/onboarding/api.py:69`, `:92`, `:113`, `:141`, `:181`) |
| La configuración referencia credenciales, nunca valores | `src/ia_mcp/configuration/models.py:28`, `:34`, `:39`, `:44` (`credentials_reference`), reforzado por el validador `:59-70` |
| Nada en `src/` resuelve una referencia `sm://` | la única lectura del esquema es una comprobación de forma: `src/ia_mcp/onboarding/preflight.py:272` |
| El único "resolvedor" falla cerrado a propósito | `src/ia_mcp/onboarding/preflight.py:455` `_FailClosedSecrets`, inyectado por defecto en `:226` |
| Ese default bloquea la activación | `secrets_resolvable` nunca pasa, así que `assert_report_allows_activation` rechaza siempre (residual documentado de P08-T03) |
| El transporte MCP ya asume que el valor se resuelve fuera | `src/ia_mcp/mcp/executor.py:55` `auth_reference`; `src/ia_mcp/mcp/client.py:504` redacta esa referencia en los mensajes de error |

`docs/01-architecture/security-and-multitenancy.md` fija el marco vigente: roles `platform_admin`, `tenant_admin`, `operator`, `auditor`; autorización por acción y tenant; el adapter de secretos devuelve el valor sólo a quien lo necesita y no aparece en excepciones ni objetos serializables (RF-037, CON-006). Esta decisión no cambia ese marco: elige el mecanismo concreto que hoy falta.

No hay proveedor de identidad, ni secret manager, ni gate `EXT` cumplido para ninguno de los dos (`docs/00-governance/assumptions-decisions-dependencies.md`). La decisión debe funcionar sin inventar ninguno.

## Decisión

### 1. Puerto de resolución de secretos

`SecretResolver` (`src/ia_mcp/configuration/secrets.py`) resuelve una referencia a su valor o falla:

```python
SECRET_SCHEME = "sm://"

class SecretResolver(Protocol):
    async def resolve(self, reference: str) -> SecretStr: ...
```

- **Devuelve `SecretStr`, no `str`.** `str()` y `repr()` rinden una máscara, así que un valor que llegue a un log, a un atributo de span o a una f-string queda enmascarado. Sólo `get_secret_value()` entrega la credencial, y sólo un transporte o una comparación debería llamarlo.
- **Falla cerrado con error tipado.** Una referencia malformada, con otro esquema o sin valor levanta `SecretResolutionError` (`DomainError`, `retryable=False`) con `code` `invalid_reference` o `secret_unresolved`. Ningún adapter puede sustituir un default, una cadena vacía ni una referencia vecina.
- **La excepción no lleva el valor.** `safe_message` es genérico ("Secret reference could not be resolved.") y `details` lleva sólo la referencia, que nombra un secreto y no lo es. El redactor ya perdona claves `*_reference` por esa misma razón (`src/ia_mcp/observability/redaction.py:19`).
- **El puerto no es tenant-scoped, y es deliberado.** Una referencia es un identificador opaco; el ownership lo decide la consulta tenant-scoped que la produjo. Ningún consumidor puede pasarle una referencia que llegó en un request.

### 2. Un adapter real: entorno del proceso

`EnvironmentSecretResolver` (`src/ia_mcp/configuration/adapters/environment_secrets.py`) mapea

```
sm://<path>  ->  IA_MCP_SECRET_<PATH>
```

donde `<PATH>` es el path en mayúsculas con `/`, `-` y `.` convertidos en `_`. `sm://tenant-b/mcp/appointments` lee `IA_MCP_SECRET_TENANT_B_MCP_APPOINTMENTS`.

Límites, que el deployment debe respetar:

- **Colapsa separadores y mayúsculas.** `sm://a/b`, `sm://a-b`, `sm://a.b` y `sm://A/B` nombran la misma variable. El adapter no puede distinguirlas; un deployment no debe usar dos que colisionen.
- **Su vida es la del proceso.** El entorno se fija en el `exec`, así que rotar un valor exige reiniciar. Nada se cachea más allá de eso: cada resolución vuelve a leer el mapping, de modo que un adapter contra un secret manager real reemplaza a éste sin tocar a sus consumidores.
- **Rechaza lo que no puede mapear.** El path admite `[A-Za-z0-9]` separados por `/`, `-` o `.`; espacios, `..` o query strings son `invalid_reference` en vez de normalizarse hacia otra variable.
- **No valida ownership.** Ver §1: ningún adapter de hoy liga una referencia a un tenant.

### 3. Token de servicio por principal

El plano administrativo autentica **por request**. El llamador presenta `Authorization: Bearer <token>`; cada principal declarado tiene un token propio, guardado como referencia `sm://` y resuelto por el puerto; el token presentado se compara contra **todos** los declarados y el binding que coincide aporta el `Principal` (id, roles y, cuando lo tiene, tenant) del request.

Roster en una variable, `IA_MCP_ADMIN_PRINCIPALS`, con entradas separadas por `,` y campos `nombre=valor` separados por `;`:

```
principal=<uuid>;roles=<rol>[|<rol>…];secret=sm://<path>[;tenant_id=<uuid>;tenant_slug=<slug>]
```

- `tenant_id` y `tenant_slug` van juntos y ligan el principal a un tenant, que es lo que `tenant_admin`, `operator` y `auditor` necesitan; un `platform_admin` se declara sin ellos.
- El roster lleva **referencias**, nunca valores: el valor vive en `IA_MCP_SECRET_*` y jamás en la configuración del proceso.
- Una entrada malformada levanta y cierra el plano completo, en vez de vincular menos principales. Un typo no degrada silenciosamente a un operador. El rechazo describe la forma y no repite lo leído, porque puede contener una credencial pegada donde iba una referencia.
- Un rol fuera de `{platform_admin, tenant_admin, operator, auditor}` es un typo o un privilegio inventado; en ambos casos se rechaza.

Comparación y fugas:

- **Tiempo constante sobre digests de ancho fijo.** Se comparan `sha256` con `secrets.compare_digest`, no los tokens: `==` filtra el prefijo por timing y `compare_digest` sobre cadenas todavía filtraría el largo.
- **Sin salida temprana.** Se recorren todos los bindings aunque uno haya coincidido, para que el trabajo no dependa de qué token se presentó.
- **Un binding irresoluble no autentica a nadie ni afecta a los demás.** Un error de operación no abre el plano ni cierra a un principal bien configurado.
- **Ningún fragmento del token sale.** No se refleja en la respuesta, no se registra y no entra en un span. El 401 responde siempre el mismo mensaje.

### 4. Códigos y fail-closed

| Situación | Código |
|---|---|
| Sin header, header no parseable, token desconocido, proceso sin roster | 401, mismo cuerpo |
| Autenticado sin el rol de la acción, o sin tenant donde hace falta | 403 |
| Autenticado y autorizado, recurso de otro tenant | 404 (sin confirmar existencia; sin cambios) |

Un token inválido y uno ausente no se distinguen: mismo status, mismo cuerpo y mismos headers salvo el de correlación. Sin roster no hay autenticador publicado y el boundary rechaza a todos; nunca "si no hay configuración, dejá pasar".

### 5. `app.state.principal` desaparece

No queda punto de inyección para una identidad ya resuelta. El punto de inyección es el **autenticador** (`app.state.admin_authenticator`), publicado por el composition root en todos los entornos: un test puede sustituirlo por uno falso, pero un proceso real no puede saltear la verificación presentando estado. Las suites presentan un header contra un `ServiceTokenAuthenticator` real cuyo único doble es el store de secretos.

### 6. Cableado

- `create_app` publica el autenticador leyendo el entorno, en todos los entornos y no sólo en desarrollo: autenticar no es una comodidad de desarrollo.
- El composition root reemplaza `_FailClosedSecrets` por `ResolvableSecretReferences`, un adapter tenant-scoped sobre el `SecretResolver`, de modo que `secrets_resolvable` reporta lo que el proceso alcanza. El CLI de onboarding compone igual, para que un `preflight` por CLI y uno por API coincidan.
- `_FailClosedSecrets` sigue siendo el default de `default_preflight_checks`: quitarlo abriría el check para quien no inyecte nada.

### 7. Rotación

Rotar un token es publicar un valor nuevo en `IA_MCP_SECRET_*` y reiniciar el proceso; el roster no cambia porque nombra una referencia, no un valor. Para rotar sin ventana de corte se declara un segundo principal (o el mismo id con otra referencia), se migran los llamadores y se retira la entrada vieja: dos bindings pueden coexistir porque la comparación recorre todos. Cambiar el valor no invalida nada retroactivamente —no hay sesión ni caché—, pero tampoco hay revocación central: hasta el reinicio el valor viejo sigue siendo el válido.

### 8. CLI

El CLI de onboarding **no** usa tokens: sigue recibiendo `--principal-id` y `--role` y construyendo un `Principal` local (`src/ia_mcp/onboarding/cli.py`). No es una excepción a la autenticación sino un límite de confianza distinto: quien corre el CLI ya tiene el `DATABASE_URL` y acceso al host, es decir más autoridad que la que cualquier token administrativo otorga. Autenticar ahí no agregaría control; sí lo agregaría restringir quién puede ejecutarlo, que es una decisión de operación, no de código. Lo que sí se unifica es la resolución de secretos: el CLI compone el mismo resolver del entorno.

## Consecuencias positivas

- Los 8 endpoints administrativos dejan de ser inalcanzables sin inventar un IdP.
- La identidad viaja en el request: un proceso puede servir a varios principales y a varios tenants, y la autorización por rol y tenant que ya existía pasa a tener sobre qué actuar.
- Las credenciales referenciadas se resuelven por un puerto único, con un adapter real y fail-closed, reutilizable por el transporte MCP y por los canales.
- `secrets_resolvable` deja de ser una negativa constante y pasa a decir la verdad sobre el deployment.
- El valor de un secreto tiene un tipo que lo enmascara por defecto, en vez de depender de que cada llamador se acuerde de redactar.

## Consecuencias negativas

- Un bearer token es un secreto portador: quien lo captura es el principal hasta que se rote. No hay expiración, ni binding a canal, ni prueba de posesión.
- No hay revocación central: retirar un principal exige cambiar el entorno y reiniciar.
- El roster es configuración de deployment; una entrada de más es un principal de más, y sólo el proceso que la lee sabe cuáles existen.
- El adapter de entorno no es un secret manager: sin rotación en caliente, sin auditoría de acceso al secreto y sin ownership por tenant.
- Un binding irresoluble se comporta igual que un token equivocado, así que un error de operación se ve como un 401 y no como un fallo de arranque.

## Alternativas descartadas

- **OIDC/JWT con un issuer externo.** Es el destino natural (`identidad federada` en `security-and-multitenancy.md`), pero exige un IdP acordado, descubrimiento de claves, rotación de JWKS, política de claims y relojes. No hay proveedor decidido; inventarlo sería inventar autenticación, lo que `AGENTS.md` prohíbe explícitamente. Además, la verificación de firma no elimina la necesidad de resolver secretos, que es el otro agujero abierto.
- **mTLS.** Autentica el workload y encaja en "servicios internos", no en un operador humano con roles y tenant asignados. Depende de una PKI, de terminación TLS que hoy no está definida y de propagar la identidad del certificado hasta la aplicación. Sigue siendo la opción correcta para el tráfico servicio-a-servicio y no queda descartada para ese boundary.
- **API keys en base de datos.** Mueve el problema: la tabla necesita un secreto para leerse, la clave necesita hashing y rotación propios, y agrega una migración y un ciclo de vida antes de tener la primera autenticación.
- **Un único token compartido de plataforma.** No puede expresar roles ni tenant, y convierte cualquier fuga en una fuga total.
- **Basic auth.** Añade una contraseña por persona sin aportar nada sobre un token de servicio, y empuja a que el navegador guarde credenciales.
- **Dejar `app.state.principal` como punto de inyección de tests.** Es un bypass de producción esperando ser configurado.

## Verificación

- Unit (`tests/unit/api/test_admin_auth.py`): parseo del roster y rechazo de cada forma malformada; el rechazo no repite la entrada; sólo el bearer exacto autentica; un binding irresoluble no autentica ni afecta a otros; se comparan todos los bindings aunque uno coincida; el módulo compara con `compare_digest`; ni el binding ni el autenticador guardan un valor.
- Unit (`tests/unit/configuration/test_secrets.py`): mapeo referencia→variable; variable ausente o en blanco falla cerrado; referencia fuera de forma es `invalid_reference`; una variable vecina no se sustituye; ninguna representación del valor lo imprime; el error no lleva ni el valor ni el nombre de la variable.
- Unit (`tests/unit/api/test_composition.py`): sin roster no se publica autenticador; con roster el token del entorno autentica; un principal sin su secreto no autentica; `create_app` publica el autenticador en todos los entornos; el runtime cablea el resolver del entorno en el check de secretos.
- Security (`tests/security/test_admin_auth.py`): las 7 rutas administrativas rechazan sin token; un token inválido es indistinguible de uno ausente; `app.state.principal` no es bypass ni gana sobre el token presentado; rol insuficiente es 403; el token de otro tenant nunca lee un run ajeno; ninguna respuesta, header ni log lleva un token ni un fragmento.
- Integration (`tests/integration/onboarding/test_preflight_secrets.py`): con las referencias exportadas `secrets_resolvable` pasa; con una faltante falla con `secret_unresolved` y sin nombrar el valor; el resto de los puertos fail-closed sigue impidiendo que el reporte pase.
- Matriz de amenazas: dos filas nuevas en `tests/fixtures/security_matrix.py` (fuga de token administrativo; IDOR de run entre tenants).

## Rollback/sustitución

Quitar `IA_MCP_ADMIN_PRINCIPALS` deja el plano cerrado (401 en todo), que es el estado previo a esta decisión y es seguro. Volver a `app.state.principal` no es un rollback aceptable: reintroduce un bypass.

La sustitución prevista es por capas y no obliga a rehacer los consumidores:

- Cambiar `EnvironmentSecretResolver` por un adapter contra un secret manager real mantiene el puerto, gana rotación en caliente y auditoría, y permite validar ownership por tenant dentro del adapter.
- Cambiar `ServiceTokenAuthenticator` por un verificador OIDC mantiene el punto de inyección (`app.state.admin_authenticator`) y el contrato `authenticate(credentials) -> Principal | None`; los routers no cambian.

## Fuera de alcance

- **Identidad por persona.** Un token identifica a un principal de servicio, no a un humano; la auditoría registra ese `principal_id`. Atribuir una acción a una persona requiere el IdP que aquí se descarta.
- **Revocación central.** No hay lista de revocación ni introspección; retirar un principal es cambiar la configuración del proceso.
- **Federación y SSO.** Sin issuer, sin claims, sin refresh.
- **Expiración y renovación automática de tokens.**
- **Autenticación del CLI** (§8) y de los servicios internos, que sigue siendo el boundary de mTLS.
- **Ownership de referencias por tenant dentro del resolver** (§1).
