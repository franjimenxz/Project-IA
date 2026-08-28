from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from ia_mcp.observability.redaction import redact
from ia_mcp.onboarding.commands import OnboardingError, Principal, load_tenant_package
from ia_mcp.onboarding.service import TenantOnboardingService, admin_context_for
from ia_mcp.onboarding.validator import validate_package
from ia_mcp.shared.errors import TenantIsolationViolation


def main(
    argv: Sequence[str] | None = None,
    *,
    service: TenantOnboardingService | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m ia_mcp.onboarding")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("package", type=Path)
    provision_parser = subparsers.add_parser("provision")
    provision_parser.add_argument("package", type=Path)
    provision_parser.add_argument("--principal-id", type=UUID, required=True)
    provision_parser.add_argument("--role", action="append", default=[])
    disable_parser = subparsers.add_parser("disable")
    disable_parser.add_argument("slug")
    disable_parser.add_argument("--principal-id", type=UUID, required=True)
    disable_parser.add_argument("--role", action="append", default=[])
    disable_parser.add_argument("--reason", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "validate":
        report = validate_package(args.package)
        print(redact(report.model_dump_json(indent=2)))
        return 0 if report.valid else 1
    if service is None:
        print("onboarding service is not configured")
        return 2
    return asyncio.run(_dispatch(args, service))


async def _dispatch(args: argparse.Namespace, service: TenantOnboardingService) -> int:
    principal = Principal(
        principal_id=args.principal_id,
        roles=frozenset(args.role),
    )
    try:
        if args.command == "provision":
            package = load_tenant_package(args.package)
            provisioned = await service.provision(package, principal)
            print(
                redact(
                    f"provisioned slug={provisioned.identity.tenant_slug} "
                    f"status={provisioned.status} config={provisioned.config_status}"
                )
            )
            return 0
        if args.command == "disable":
            tenant = await service.get_by_slug(args.slug)
            if tenant is None:
                print("tenant is not available")
                return 1
            await service.disable(
                admin_context_for(principal, tenant),
                args.reason,
            )
            print(redact(f"disabled slug={args.slug}"))
            return 0
    except OnboardingError as exc:
        print(redact(exc.safe_message))
        return 1
    except TenantIsolationViolation:
        print("tenant is not available")
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
