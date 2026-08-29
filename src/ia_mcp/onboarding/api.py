"""Onboarding HTTP boundary.

`package_path` is caller input, so it is never handed to the loader as given:
it is resolved inside the root the deployment configured
(`IA_MCP_TENANT_PACKAGES_DIR`, published by the composition root as
`app.state.tenant_packages_dir`) and refused when it lands outside. The rule
lives here and not in `load_tenant_package`, which the CLI calls with the
operator's own local paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ia_mcp.onboarding.commands import (
    OnboardingError,
    Principal,
    ProvisionedTenant,
    load_tenant_package,
)
from ia_mcp.onboarding.service import (
    PLATFORM_ADMIN,
    TenantOnboardingService,
    admin_context_for,
    tenant_context_for,
)
from ia_mcp.onboarding.validator import validate_package
from ia_mcp.shared.errors import TenantIsolationViolation


class DisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_hash: str = Field(min_length=64, max_length=64)


class ProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_path: str = Field(min_length=1)


class PreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_path: str = Field(min_length=1)


# Neither message names a filesystem path: the response must not describe the
# server's layout, and an outside path must not be distinguishable from an
# absent one.
_UNCONFIGURED_ROOT = "Tenant package intake is not enabled."
_UNAVAILABLE_PACKAGE = "Tenant package is not available."


def create_onboarding_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/admin/tenants/provision")
    async def provision_tenant(
        request: Request,
        payload: ProvisionRequest,
        principal: Annotated[Principal, Depends(_get_principal)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> dict[str, str]:
        if PLATFORM_ADMIN not in principal.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator is not allowed to perform this action.",
            )
        root = _packages_root(request)
        try:
            package = load_tenant_package(_package_inside(root, payload.package_path))
            tenant = await service.provision(package, principal)
        except OnboardingError as exc:
            raise HTTPException(
                status_code=_status_for(exc),
                detail=exc.safe_message,
            ) from exc
        return _tenant_body(tenant)

    @router.get("/v1/admin/tenants/{slug}")
    async def get_tenant(
        slug: str,
        principal: Annotated[Principal, Depends(_get_principal)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> dict[str, str]:
        tenant = await service.get_by_slug(slug)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            )
        try:
            admin_context_for(principal, tenant)
        except (OnboardingError, TenantIsolationViolation) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc
        return _tenant_body(tenant)

    @router.post("/v1/admin/tenants/{slug}/disable")
    async def disable_tenant(
        slug: str,
        payload: DisableRequest,
        principal: Annotated[Principal, Depends(_get_principal)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> dict[str, str]:
        tenant = await service.get_by_slug(slug)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            )
        try:
            admin = admin_context_for(principal, tenant)
            await service.disable(admin, payload.reason)
        except OnboardingError as exc:
            raise HTTPException(
                status_code=_status_for(exc),
                detail=exc.safe_message,
            ) from exc
        except TenantIsolationViolation as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc
        return _tenant_body(tenant)

    @router.post("/v1/admin/tenants/{slug}/preflight")
    async def preflight_tenant(
        slug: str,
        request: Request,
        payload: PreflightRequest,
        principal: Annotated[Principal, Depends(_get_principal)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> dict[str, str | bool]:
        tenant = await service.get_by_slug(slug)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            )
        try:
            admin = admin_context_for(principal, tenant)
            root = _packages_root(request)
            validation = validate_package(_package_inside(root, payload.package_path))
            if validation.content_hash is None:
                raise OnboardingError("invalid_preflight", "A content hash is required.")
            report = await service.preflight(
                tenant_context_for(tenant, correlation_id=admin.correlation_id),
                content_hash=validation.content_hash,
            )
        except OnboardingError as exc:
            raise HTTPException(
                status_code=_status_for(exc),
                detail=exc.safe_message,
            ) from exc
        except TenantIsolationViolation as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc
        return {
            "report_hash": report.report_hash,
            "passed": report.passed,
            "content_hash": report.content_hash,
        }

    @router.post("/v1/admin/tenants/{slug}/activate")
    async def activate_tenant(
        slug: str,
        payload: ActivateRequest,
        principal: Annotated[Principal, Depends(_get_principal)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> dict[str, str]:
        tenant = await service.get_by_slug(slug)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            )
        try:
            admin = admin_context_for(principal, tenant)
            await service.activate(admin, payload.report_hash)
        except OnboardingError as exc:
            raise HTTPException(
                status_code=_status_for(exc),
                detail=exc.safe_message,
            ) from exc
        except TenantIsolationViolation as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            ) from exc
        updated = await service.get_by_slug(slug)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            )
        return _tenant_body(updated)

    return router


def _tenant_body(tenant: ProvisionedTenant) -> dict[str, str]:
    return {
        "tenant_id": str(tenant.identity.tenant_id),
        "slug": tenant.identity.tenant_slug,
        "status": tenant.status,
    }


def _packages_root(request: Request) -> Path:
    """Directory this deployment opted into for tenant packages.

    Fail closed: without a usable root the endpoint refuses instead of
    accepting the caller's path, so an unconfigured process never becomes a
    remote read primitive.
    """
    root = getattr(request.app.state, "tenant_packages_dir", None)
    if not isinstance(root, Path):
        raise _intake_disabled()
    try:
        resolved = root.resolve()
        usable = resolved.is_dir()
    except (OSError, ValueError, RuntimeError) as exc:
        raise _intake_disabled() from exc
    if not usable:
        raise _intake_disabled()
    return resolved


def _package_inside(root: Path, requested: str) -> Path:
    """Resolve `requested` and keep it inside `root`, or refuse.

    Symlinks are followed before the comparison: rejecting `..` textually would
    still accept a link stored inside the root that points anywhere on the
    host. `root` arrives resolved, so both sides are compared symlink-free.
    """
    try:
        candidate = Path(requested)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        contained = resolved.is_relative_to(root) and resolved.is_dir()
    except (OSError, ValueError, RuntimeError) as exc:
        raise _unavailable_package() from exc
    if not contained:
        raise _unavailable_package()
    return resolved


def _intake_disabled() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_UNCONFIGURED_ROOT,
    )


def _unavailable_package() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=_UNAVAILABLE_PACKAGE,
    )


def _get_service(request: Request) -> TenantOnboardingService:
    service = getattr(request.app.state, "onboarding_service", None)
    if not isinstance(service, TenantOnboardingService):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred",
        )
    return service


def _get_principal(request: Request) -> Principal:
    principal = getattr(request.app.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator identity is required.",
        )
    return principal


def _status_for(exc: OnboardingError) -> int:
    if exc.code == "forbidden":
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_400_BAD_REQUEST
