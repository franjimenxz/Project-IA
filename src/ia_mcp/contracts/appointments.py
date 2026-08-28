from datetime import date
from enum import StrEnum
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    SecretStr,
    model_validator,
)

from ia_mcp.contracts.common import NonEmptyStr


class AppointmentStatus(StrEnum):
    SCHEDULED = "scheduled"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


class AppointmentSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    specialty: NonEmptyStr
    date_from: date
    date_to: date
    practitioner: NonEmptyStr | None = None
    location: NonEmptyStr | None = None
    coverage: NonEmptyStr | None = None

    @model_validator(mode="after")
    def date_range_is_ordered(self) -> Self:
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self


class AppointmentSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: NonEmptyStr
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    specialty: NonEmptyStr
    practitioner: NonEmptyStr | None = None
    location: NonEmptyStr | None = None
    booking_token: SecretStr | None = None

    @model_validator(mode="after")
    def interval_is_positive(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class PatientRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_patient_id: NonEmptyStr | None = None
    document_type: NonEmptyStr | None = None
    document_number: SecretStr | None = None
    name: NonEmptyStr | None = None
    email: EmailStr | None = None


class Patient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: NonEmptyStr | None = None
    document_type: NonEmptyStr | None = None
    document_number: SecretStr | None = None
    name: NonEmptyStr | None = None
    email: EmailStr | None = None
    coverage: NonEmptyStr | None = None


class AppointmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    slot_id: NonEmptyStr
    booking_token: SecretStr | None = None
    patient: PatientRef
    coverage: NonEmptyStr | None = None
    contact_email: EmailStr | None = None


class Appointment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    appointment_id: NonEmptyStr
    status: AppointmentStatus
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    specialty: NonEmptyStr
    practitioner: NonEmptyStr | None = None
    location: NonEmptyStr | None = None

    @model_validator(mode="after")
    def interval_is_positive(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AppointmentGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    appointment_id: NonEmptyStr


class AppointmentCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    appointment_id: NonEmptyStr
    reason: NonEmptyStr | None = None


class AppointmentRescheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    appointment_id: NonEmptyStr
    new_slot_id: NonEmptyStr
    booking_token: SecretStr | None = None


class AppointmentConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    appointment_id: NonEmptyStr
    confirmed: Literal[True] = True
