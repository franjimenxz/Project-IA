"""Appointment e2e collector for the Phase 4 test-plan path.

Slice suites remain in test_appointment_*.py; this module re-exports them so
`pytest -m e2e tests/e2e/test_appointments.py` matches test-plan.md.
"""

from __future__ import annotations

from tests.e2e.test_appointment_cancel import (  # noqa: F401
    test_already_cancelled_completes_without_error,
    test_concurrent_confirms_cancel_one_appointment,
    test_confirm_cancel_replay_cancels_once,
)
from tests.e2e.test_appointment_create import (  # noqa: F401
    db,
    test_concurrent_confirms_create_one_appointment,
    test_confirm_create_replay_creates_one_appointment,
)
from tests.e2e.test_appointment_lifecycle import (  # noqa: F401
    test_concurrent_reschedule_mutates_once,
    test_confirm_replay_confirms_once,
    test_lost_slot_keeps_original_appointment,
    test_reschedule_replay_mutates_once,
    test_tenant_a_cannot_mutate_tenant_b_appointment,
)
