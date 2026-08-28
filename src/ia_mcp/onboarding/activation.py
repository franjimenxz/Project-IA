from __future__ import annotations

from typing import assert_never

from ia_mcp.onboarding.commands import OnboardingError
from ia_mcp.onboarding.preflight import CheckOutcome, PreflightReport


def assert_report_allows_activation(
    report: PreflightReport,
    *,
    content_hash: str,
    config_hash: str,
) -> None:
    if report.content_hash != content_hash or report.config_hash != config_hash:
        raise OnboardingError(
            "stale_preflight",
            "Preflight evidence does not match current content.",
        )
    if not report.passed:
        raise OnboardingError("preflight_failed", "Preflight did not pass.")
    for check in report.checks:
        if check.passed:
            continue
        _reject_failed_check(check)


def _reject_failed_check(check: CheckOutcome) -> None:
    match check.severity:
        case "critical":
            raise OnboardingError("preflight_failed", "Preflight did not pass.")
        case "warning":
            raise OnboardingError("preflight_failed", "Preflight did not pass.")
        case _ as unreachable:
            assert_never(unreachable)
