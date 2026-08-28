from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from ia_mcp.onboarding.service import classify_provision_integrity


def _integrity(constraint_name: str) -> IntegrityError:
    class Diag:
        def __init__(self, name: str) -> None:
            self.constraint_name = name

    class Orig(Exception):
        def __init__(self, name: str) -> None:
            super().__init__(f'duplicate key value violates unique constraint "{name}"')
            self.diag = Diag(name)
            self.sqlstate = "23505"

    return IntegrityError("INSERT", {}, Orig(constraint_name))


def test_slug_unique_violation_is_replay_not_channel_conflict() -> None:
    kind = classify_provision_integrity(_integrity("tenant_slug_key"))
    assert kind == "slug_race"


def test_channel_unique_violation_is_channel_conflict() -> None:
    kind = classify_provision_integrity(
        _integrity("channel_integration_channel_external_account_id_key")
    )
    assert kind == "channel_conflict"
