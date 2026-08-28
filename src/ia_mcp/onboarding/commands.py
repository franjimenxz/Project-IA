from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from ia_mcp.onboarding.loader import load_package
from ia_mcp.onboarding.models import (
    IntegrationsDocument,
    KnowledgeManifest,
    PackageConfig,
    PackageEvalCase,
    PolicyDocument,
    TenantDocument,
    TenantPackage,
)
from ia_mcp.onboarding.validator import validate_package
from ia_mcp.shared.errors import DomainError
from ia_mcp.tenancy.models import TenantIdentity

type TenantLifecycleStatus = Literal["provisioning", "active", "suspended", "disabled"]
type ConfigLifecycleStatus = Literal["draft", "validated", "published", "retired"]


class OnboardingError(DomainError):
    def __init__(self, code: str, safe_message: str, retryable: bool = False) -> None:
        super().__init__(code, safe_message, retryable)


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: UUID
    roles: frozenset[str]
    tenant_id: UUID | None = None
    tenant_slug: str | None = None


@dataclass(frozen=True, slots=True)
class ProvisionedTenant:
    identity: TenantIdentity
    status: TenantLifecycleStatus
    config_version: int
    config_status: ConfigLifecycleStatus


def load_tenant_package(root: Path) -> TenantPackage:
    report = validate_package(root)
    if not report.valid:
        raise OnboardingError(
            "invalid_package",
            "Tenant package is not valid.",
        )
    loaded = load_package(root)
    return TenantPackage(
        tenant=TenantDocument.model_validate(loaded.tenant),
        config=PackageConfig.model_validate(loaded.config),
        policies=tuple(
            PolicyDocument.model_validate(body) for body in loaded.policies.values()
        ),
        knowledge=KnowledgeManifest.model_validate(loaded.knowledge),
        integrations=IntegrationsDocument.model_validate(loaded.integrations),
        evals=tuple(PackageEvalCase.model_validate(row) for row in loaded.evals),
    )
