# TDD — Contratos canónicos y MCP

**ID:** TDD-P03-001  
**Estado:** ready  
**Requisitos:** RF-016–RF-027, RNF-010, RNF-011, RNF-015  
**ADR:** ADR-003

## Convenciones

- Pydantic v2 con `extra="forbid"`.
- `schema_version: Literal[1]` en envelopes versionables.
- Fechas/timestamps ISO 8601; timezone requerida en instantes.
- IDs externos son strings opacos; no se interpretan.
- Enums versionados y desconocidos producen contract violation.
- Contratos de tool no incluyen tenant ni credenciales; el runtime los inyecta fuera del modelo.

## Contratos principales

```python
class AppointmentSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    specialty: NonEmptyStr
    date_from: date
    date_to: date
    practitioner: NonEmptyStr | None = None
    location: NonEmptyStr | None = None
    coverage: NonEmptyStr | None = None

class AppointmentSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot_id: NonEmptyStr
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    specialty: NonEmptyStr
    practitioner: NonEmptyStr | None = None
    location: NonEmptyStr | None = None
    booking_token: SecretStr | None = None

class PatientRef(BaseModel):
    external_patient_id: NonEmptyStr | None = None
    document_type: NonEmptyStr | None = None
    document_number: SecretStr | None = None
    name: NonEmptyStr | None = None
    email: EmailStr | None = None

class Patient(BaseModel):
    patient_id: NonEmptyStr
    document_type: NonEmptyStr | None = None
    document_number: SecretStr | None = None
    name: NonEmptyStr
    email: EmailStr | None = None
    coverage: NonEmptyStr | None = None

class AppointmentCreateRequest(BaseModel):
    schema_version: Literal[1] = 1
    slot_id: NonEmptyStr
    booking_token: SecretStr | None = None
    patient: PatientRef
    coverage: NonEmptyStr | None = None
    contact_email: EmailStr | None = None

class Appointment(BaseModel):
    appointment_id: NonEmptyStr
    status: AppointmentStatus
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    specialty: NonEmptyStr
    practitioner: NonEmptyStr | None = None
    location: NonEmptyStr | None = None
```

`PatientRef` representa datos aportados o una referencia parcial para una operación. `Patient` representa la respuesta canónica de una capability externa; el Core no la convierte automáticamente en un registro maestro persistente.

Validaciones cruzadas:

- `date_from <= date_to` y rango máximo configurable por policy, no hardcodeado en schema;
- `ends_at > starts_at`;
- crear requiere los campos configurados antes de invocar tool;
- al menos un identificador permitido para localizar paciente/turno según capability.

## Resultados y errores

```python
class ToolError(BaseModel):
    code: ToolErrorCode
    retryable: bool
    safe_message: str
    upstream_reference: str | None = None

class ToolResult[T](BaseModel):
    ok: bool
    value: T | None = None
    error: ToolError | None = None
```

El validator exige exactamente uno de `value` o `error` según `ok`. `upstream_reference` es opaca y sanitizada.

## Tool catalog

| Tool | Input | Output | Mutación | Idempotency |
|---|---|---|---|---|
| `appointments.search` | AppointmentSearchRequest | list[AppointmentSlot] | no | request hash opcional |
| `appointments.get` | AppointmentGetRequest | Appointment | no | no |
| `appointments.create` | AppointmentCreateRequest | Appointment | sí | obligatoria |
| `appointments.cancel` | AppointmentCancelRequest | Appointment | sí | obligatoria |
| `appointments.reschedule` | AppointmentRescheduleRequest | Appointment | sí | obligatoria |
| `appointments.confirm` | AppointmentConfirmRequest | Appointment | sí | obligatoria |

## Tool Registry

`available = server_capabilities ∩ tenant_config.enabled_tools ∩ skill.allowed_tools`. Una llamada se vuelve a validar al ejecutar. Tool desconocida o fuera de allowlist devuelve `forbidden`, no se reenvía.

## Fake MCP

Fake agenda mantiene slots/appointments en memoria por tenant para unit/E2E, con reloj y UUID inyectados. Implementa búsqueda, alta, cancelación, reprogramación y confirmación; simula errores mediante fault plan tipado. Nunca se usa como adapter productivo.

## Compatibilidad

Cambio aditivo opcional conserva versión. Campo obligatorio, semántica o enum incompatible incrementa schema/tool version. El Core soporta una ventana explícita de versiones durante migración.

## Seguridad

SecretStr evita representación accidental; redactor procesa summaries. Contratos del modelo no incluyen `tenant_id`, endpoint o credential reference. Requests se limitan en tamaño y strings normalizados.
