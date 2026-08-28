import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from ia_mcp.contracts.appointments import (
    Appointment,
    AppointmentCancelRequest,
    AppointmentConfirmRequest,
    AppointmentCreateRequest,
    AppointmentGetRequest,
    AppointmentRescheduleRequest,
    AppointmentSearchRequest,
    AppointmentSlot,
    AppointmentStatus,
    Patient,
    PatientRef,
)

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
FORBIDDEN_SCHEMA_FIELDS = frozenset(
    {"tenant_id", "endpoint", "credentials_reference", "credentials"}
)

SEARCH_PAYLOAD: dict[str, Any] = {
    "specialty": "cardiologia",
    "date_from": "2026-09-01",
    "date_to": "2026-09-05",
}
SLOT_PAYLOAD: dict[str, Any] = {
    "slot_id": "slot-1",
    "starts_at": "2026-09-01T13:00:00Z",
    "ends_at": "2026-09-01T13:30:00Z",
    "specialty": "cardiologia",
    "booking_token": "tok-secret-value",
}
APPOINTMENT_PAYLOAD: dict[str, Any] = {
    "appointment_id": "apt-1",
    "status": "scheduled",
    "starts_at": "2026-09-01T13:00:00Z",
    "ends_at": "2026-09-01T13:30:00Z",
    "specialty": "cardiologia",
}

TOOL_REQUESTS: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (AppointmentSearchRequest, SEARCH_PAYLOAD),
    (AppointmentGetRequest, {"appointment_id": "apt-1"}),
    (AppointmentCreateRequest, {"slot_id": "slot-1", "patient": {}}),
    (AppointmentCancelRequest, {"appointment_id": "apt-1"}),
    (
        AppointmentRescheduleRequest,
        {"appointment_id": "apt-1", "new_slot_id": "slot-2"},
    ),
    (AppointmentConfirmRequest, {"appointment_id": "apt-1"}),
]

SCHEMA_MODELS: tuple[type[BaseModel], ...] = (
    AppointmentSearchRequest,
    AppointmentSlot,
    PatientRef,
    Patient,
    AppointmentCreateRequest,
    Appointment,
    AppointmentGetRequest,
    AppointmentCancelRequest,
    AppointmentRescheduleRequest,
    AppointmentConfirmRequest,
)


def test_search_rejects_reversed_dates() -> None:
    with pytest.raises(ValidationError):
        AppointmentSearchRequest(
            specialty="cardiologia",
            date_from=date(2026, 9, 5),
            date_to=date(2026, 9, 1),
        )


def test_search_accepts_ordered_dates() -> None:
    request = AppointmentSearchRequest.model_validate(SEARCH_PAYLOAD)
    assert request.schema_version == 1
    assert request.specialty == "cardiologia"
    assert request.date_from == date(2026, 9, 1)
    assert request.date_to == date(2026, 9, 5)


def test_search_accepts_equal_dates() -> None:
    request = AppointmentSearchRequest(
        specialty="cardiologia",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 1),
    )
    assert request.date_from == request.date_to


def test_slot_rejects_naive_starts_at() -> None:
    payload = dict(SLOT_PAYLOAD)
    payload["starts_at"] = "2026-09-01T13:00:00"
    with pytest.raises(ValidationError):
        AppointmentSlot.model_validate(payload)


def test_slot_rejects_end_before_start() -> None:
    payload = dict(SLOT_PAYLOAD)
    payload["starts_at"] = "2026-09-01T13:30:00Z"
    payload["ends_at"] = "2026-09-01T13:00:00Z"
    with pytest.raises(ValidationError):
        AppointmentSlot.model_validate(payload)


def test_slot_rejects_equal_start_and_end() -> None:
    payload = dict(SLOT_PAYLOAD)
    payload["ends_at"] = payload["starts_at"]
    with pytest.raises(ValidationError):
        AppointmentSlot.model_validate(payload)


def test_appointment_rejects_end_before_start() -> None:
    payload = dict(APPOINTMENT_PAYLOAD)
    payload["starts_at"] = "2026-09-01T14:00:00Z"
    payload["ends_at"] = "2026-09-01T13:00:00Z"
    with pytest.raises(ValidationError):
        Appointment.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload"),
    TOOL_REQUESTS,
    ids=lambda value: value.__name__ if isinstance(value, type) else "",
)
@pytest.mark.parametrize("extra_field", ["tenant_id", "credentials"])
def test_tool_requests_reject_extra_tenant_or_credentials(
    model: type[BaseModel],
    payload: dict[str, Any],
    extra_field: str,
) -> None:
    invalid = dict(payload)
    invalid[extra_field] = "leaked"
    with pytest.raises(ValidationError):
        model.model_validate(invalid)


def test_create_rejects_extra_fields_on_nested_patient() -> None:
    with pytest.raises(ValidationError):
        AppointmentCreateRequest.model_validate(
            {
                "slot_id": "slot-1",
                "patient": {"credentials": "token"},
            }
        )


def test_patient_permits_absent_name_and_id() -> None:
    patient = Patient()
    assert patient.patient_id is None
    assert patient.name is None
    assert patient.document_number is None


def test_patient_ref_permits_partial_identity() -> None:
    ref = PatientRef()
    assert ref.external_patient_id is None
    assert ref.name is None


def test_workflow_policy_can_require_configured_patient_fields() -> None:
    patient = Patient()
    required_fields = ("patient_id", "name")
    missing = [field for field in required_fields if getattr(patient, field) is None]
    assert missing == ["patient_id", "name"]

    identified = Patient(patient_id="pat-1", name="Ada")
    missing = [field for field in required_fields if getattr(identified, field) is None]
    assert missing == []


def test_booking_token_secret_str_is_redacted() -> None:
    slot = AppointmentSlot.model_validate(SLOT_PAYLOAD)
    dumped = slot.model_dump(mode="json")
    serialized = slot.model_dump_json()
    assert dumped["booking_token"] == "**********"
    assert "tok-secret-value" not in serialized
    assert "tok-secret-value" not in str(dumped)
    assert slot.booking_token is not None
    assert slot.booking_token.get_secret_value() == "tok-secret-value"


def test_document_number_secret_str_is_redacted() -> None:
    patient = Patient(document_number="secret-dni-999")
    dumped = patient.model_dump(mode="json")
    serialized = patient.model_dump_json()
    assert dumped["document_number"] == "**********"
    assert "secret-dni-999" not in serialized
    assert patient.document_number is not None
    assert patient.document_number.get_secret_value() == "secret-dni-999"


def test_unknown_appointment_status_is_rejected() -> None:
    payload = dict(APPOINTMENT_PAYLOAD)
    payload["status"] = "checked_in"
    with pytest.raises(ValidationError):
        Appointment.model_validate(payload)


def test_appointment_status_values() -> None:
    assert {status.value for status in AppointmentStatus} == {
        "scheduled",
        "pending_confirmation",
        "confirmed",
        "cancelled",
        "rescheduled",
    }


def test_confirm_rejects_confirmed_false() -> None:
    with pytest.raises(ValidationError):
        AppointmentConfirmRequest.model_validate(
            {"appointment_id": "apt-1", "confirmed": False}
        )


def test_search_rejects_invalid_schema_version() -> None:
    payload = dict(SEARCH_PAYLOAD)
    payload["schema_version"] = 2
    with pytest.raises(ValidationError):
        AppointmentSearchRequest.model_validate(payload)


def test_empty_specialty_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AppointmentSearchRequest.model_validate(
            {"specialty": " ", "date_from": "2026-09-01", "date_to": "2026-09-05"}
        )


def test_aware_datetimes_are_accepted() -> None:
    slot = AppointmentSlot(
        slot_id="slot-1",
        starts_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 1, 10, 30, tzinfo=UTC),
        specialty="cardiologia",
    )
    assert slot.starts_at.tzinfo is not None
    assert slot.ends_at > slot.starts_at


def _property_names(schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    properties = schema.get("properties")
    if isinstance(properties, dict):
        names.update(properties)
        for subschema in properties.values():
            if isinstance(subschema, dict):
                names.update(_property_names(subschema))
    for key in ("$defs", "definitions"):
        defs = schema.get(key)
        if isinstance(defs, dict):
            for subschema in defs.values():
                if isinstance(subschema, dict):
                    names.update(_property_names(subschema))
    return names


@pytest.mark.parametrize("model", SCHEMA_MODELS, ids=lambda model: model.__name__)
def test_json_schema_snapshots_omit_tenant_and_credentials(
    model: type[BaseModel],
) -> None:
    schema = model.model_json_schema()
    snapshot_path = SNAPSHOT_DIR / f"{model.__name__}.schema.json"
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert schema == expected
    assert FORBIDDEN_SCHEMA_FIELDS.isdisjoint(_property_names(schema))
