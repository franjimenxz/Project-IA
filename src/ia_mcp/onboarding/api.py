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


def create_onboarding_router() -> APIRouter:
    router = APIRouter()

    @router.post("/v1/admin/tenants/provision")
    async def provision_tenant(
        payload: ProvisionRequest,
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
        principal: Annotated[Principal, Depends(_get_principal)],
    ) -> dict[str, str]:
        if PLATFORM_ADMIN not in principal.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator is not allowed to perform this action.",
            )
        try:
            package = load_tenant_package(Path(payload.package_path))
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
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
        principal: Annotated[Principal, Depends(_get_principal)],
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
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
        principal: Annotated[Principal, Depends(_get_principal)],
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
        payload: PreflightRequest,
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
        principal: Annotated[Principal, Depends(_get_principal)],
    ) -> dict[str, str | bool]:
        tenant = await service.get_by_slug(slug)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found",
            )
        try:
            admin = admin_context_for(principal, tenant)
            validation = validate_package(Path(payload.package_path))
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
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
        principal: Annotated[Principal, Depends(_get_principal)],
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
