"""Lab HTML and JSON routes for institutions (ADR-009).

Mounted only in development and test. Auth is ADR-007 (`get_principal`).
Tenant-scoped work always receives a `TenantContext` of the chosen slug.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from string import Template
from typing import Annotated
from urllib.parse import parse_qs
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from ia_mcp.api.auth.admin import get_principal
from ia_mcp.configuration.models import (
    AgentConfig,
    McpConfig,
    TenantAdminContext,
    TenantConfigDraft,
)
from ia_mcp.configuration.ports import ConfigurationError
from ia_mcp.configuration.service import ConfigurationService
from ia_mcp.conversation.models import InboundMessage
from ia_mcp.mcp.registry import KNOWN_TOOLS
from ia_mcp.observability.context import current_correlation_id
from ia_mcp.onboarding.commands import (
    OnboardingError,
    Principal,
    ProvisionedTenant,
    load_tenant_package,
)
from ia_mcp.onboarding.lab_package import (
    InstitucionForm,
    display_name_for,
    write_lab_package,
)
from ia_mcp.onboarding.service import (
    PLATFORM_ADMIN,
    TenantListItem,
    TenantOnboardingService,
    admin_context_for,
)
from ia_mcp.onboarding.validator import validate_package
from ia_mcp.shared.errors import TenantIsolationViolation

_LIST_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "instituciones.html"
_CHAT_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "institucion_chat.html"
_UNAUTHORIZED = "Administrator is not allowed to perform this action."
_HISTORY_PAIRS = 20


def create_instituciones_router() -> APIRouter:
    router = APIRouter()

    @router.get("/v1/admin/tenants")
    async def list_tenants_json(
        principal: Annotated[Principal, Depends(require_platform_admin)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> list[dict[str, str | int]]:
        items = await service.list_tenants(principal)
        return [_item_body(item) for item in items]

    @router.post("/v1/admin/instituciones")
    async def create_institucion_json(
        request: Request,
        principal: Annotated[Principal, Depends(require_platform_admin)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
        payload: InstitucionForm,
    ) -> dict[str, str]:
        tenant = await _save_institucion(request, principal, service, payload)
        return {
            "tenant_id": str(tenant.identity.tenant_id),
            "slug": tenant.identity.tenant_slug,
            "status": tenant.status,
        }

    @router.post("/v1/admin/tenants/{slug}/lab-enable")
    async def lab_enable_tenant(
        slug: str,
        principal: Annotated[Principal, Depends(require_platform_admin)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> dict[str, str]:
        tenant = await service.get_by_slug(slug)
        if tenant is None:
            raise _not_found()
        try:
            admin = admin_context_for(principal, tenant)
            updated = await service.lab_enable(admin)
        except OnboardingError as exc:
            raise HTTPException(
                status_code=_status_for(exc),
                detail=exc.safe_message,
            ) from exc
        except TenantIsolationViolation as exc:
            raise _not_found() from exc
        return {
            "tenant_id": str(updated.identity.tenant_id),
            "slug": updated.identity.tenant_slug,
            "status": updated.status,
        }

    @router.get("/admin/instituciones", response_model=None)
    async def get_instituciones_html(
        request: Request,
        principal: Annotated[Principal, Depends(require_platform_admin)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> HTMLResponse:
        items = await service.list_tenants(principal)
        return HTMLResponse(content=_render_list(request, items, message=""))

    @router.post("/admin/instituciones", response_model=None)
    async def post_instituciones_html(
        request: Request,
        principal: Annotated[Principal, Depends(require_platform_admin)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> HTMLResponse:
        message = ""
        try:
            form = await _form_from_request(request)
            await _save_institucion(request, principal, service, form)
        except ValidationError as exc:
            message = escape(exc.errors()[0]["msg"], quote=True) if exc.errors() else "invalid"
        except HTTPException as exc:
            if exc.status_code >= 500:
                raise
            message = escape(str(exc.detail), quote=True)
        except OnboardingError as exc:
            message = escape(exc.safe_message, quote=True)
        items = await service.list_tenants(principal)
        return HTMLResponse(content=_render_list(request, items, message=message))

    @router.get("/admin/instituciones/{slug}/chat", response_model=None)
    async def get_institucion_chat(
        slug: str,
        request: Request,
        principal: Annotated[Principal, Depends(get_principal)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> HTMLResponse:
        await _chat_admin(principal, service, slug)
        return HTMLResponse(
            content=_render_chat(
                request,
                slug,
                history=(),
                error="",
            )
        )

    @router.post("/admin/instituciones/{slug}/chat", response_model=None)
    async def post_institucion_chat(
        slug: str,
        request: Request,
        principal: Annotated[Principal, Depends(get_principal)],
        service: Annotated[TenantOnboardingService, Depends(_get_service)],
    ) -> HTMLResponse:
        await _chat_admin(principal, service, slug)
        form = await _read_form(request)
        text = (form.get("text") or [""])[0].strip()
        history = _parse_history((form.get("history") or [""])[0])
        error = ""
        if text:
            try:
                reply = await _run_chat_turn(request, service, slug, text)
                history = _append_pair(history, user=text, bot=reply)
            except ConfigurationError as exc:
                error = escape(exc.safe_message, quote=True)
                history = _append_pair(history, user=text, bot=exc.safe_message)
            except OnboardingError as exc:
                raise HTTPException(
                    status_code=_status_for(exc),
                    detail=exc.safe_message,
                ) from exc
            except TenantIsolationViolation as exc:
                raise _not_found() from exc
        return HTMLResponse(
            content=_render_chat(request, slug, history=history, error=error)
        )

    return router


async def require_platform_admin(request: Request) -> Principal:
    principal = await get_principal(request)
    if PLATFORM_ADMIN not in principal.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_UNAUTHORIZED,
        )
    return principal


async def _chat_admin(
    principal: Principal, service: TenantOnboardingService, slug: str
) -> TenantAdminContext:
    tenant = await service.get_by_slug(slug)
    if tenant is None:
        raise _not_found()
    try:
        return admin_context_for(principal, tenant)
    except TenantIsolationViolation as exc:
        raise _not_found() from exc
    except OnboardingError as exc:
        if exc.code == "forbidden":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=exc.safe_message,
            ) from exc
        raise HTTPException(
            status_code=_status_for(exc),
            detail=exc.safe_message,
        ) from exc


async def _save_institucion(
    request: Request,
    principal: Principal,
    service: TenantOnboardingService,
    form: InstitucionForm,
) -> ProvisionedTenant:
    root = _packages_root(request)
    existing = await service.get_by_slug(form.slug)
    package_path = write_lab_package(root, form)
    report = validate_package(package_path)
    if not report.valid:
        raise OnboardingError("invalid_package", "Tenant package is not valid.")
    package = load_tenant_package(package_path)
    tenant = await service.provision(package, principal)
    if existing is not None:
        admin = admin_context_for(principal, tenant)
        configs = _config_service(request)
        if configs is not None:
            await configs.publish(admin, _draft_from_form(form))
    admin = admin_context_for(principal, tenant)
    return await service.lab_enable(admin)


async def _run_chat_turn(
    request: Request,
    service: TenantOnboardingService,
    slug: str,
    text: str,
) -> str:
    tenant = await service.get_by_slug(slug)
    if tenant is None:
        raise _not_found()
    configs = _config_service(request)
    harness = getattr(request.app.state, "agent_harness", None)
    if configs is None or harness is None or not hasattr(harness, "handle_message"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred",
        )
    correlation = _correlation_id(request)
    context, _config = await configs.capture(tenant.identity, correlation)
    channel_id = await service.simulated_channel_id(context)
    result = await harness.handle_message(
        context,
        InboundMessage(
            channel="simulated",
            channel_account_id=f"{slug}-simulated",
            channel_integration_id=channel_id,
            external_message_id=str(uuid4()),
            external_user_id="lab-operator",
            text=text,
            occurred_at=datetime.now(UTC),
        ),
    )
    return str(result.text)


def _draft_from_form(form: InstitucionForm) -> TenantConfigDraft:
    return TenantConfigDraft(
        schema_version=1,
        agent=AgentConfig(tone=form.tone, instructions=form.instructions),
        enabled_skills=form.enabled_skills,
        enabled_tools=form.enabled_tools,
        mcp=McpConfig(credentials_reference=form.mcp_credentials_reference),
        feature_flags={"simulated_channel": True},
    )


async def _read_form(request: Request) -> dict[str, list[str]]:
    """Parse `application/x-www-form-urlencoded` without python-multipart."""
    body = (await request.body()).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: list(values) for key, values in parsed.items()}


async def _form_from_request(request: Request) -> InstitucionForm:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValidationError.from_exception_data("InstitucionForm", [])
        return InstitucionForm.model_validate(payload)
    form = await _read_form(request)
    instructions = (form.get("instructions") or [""])[0]
    knowledge_text = (form.get("knowledge_text") or [""])[0]
    return InstitucionForm.model_validate(
        {
            "slug": (form.get("slug") or [""])[0],
            "display_name": (form.get("display_name") or [""])[0],
            "tone": (form.get("tone") or [""])[0],
            "instructions": instructions or None,
            "enabled_skills": [item for item in form.get("enabled_skills", []) if item],
            "enabled_tools": [item for item in form.get("enabled_tools", []) if item],
            "mcp_server_id": (form.get("mcp_server_id") or [""])[0],
            "mcp_capabilities": [
                item for item in form.get("mcp_capabilities", []) if item
            ],
            "mcp_credentials_reference": (
                form.get("mcp_credentials_reference") or [""]
            )[0],
            "knowledge_text": knowledge_text or None,
        }
    )


def _packages_root(request: Request) -> Path:
    root = getattr(request.app.state, "tenant_packages_dir", None)
    if not isinstance(root, Path):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant package intake is not enabled.",
        )
    try:
        resolved = root.resolve()
        usable = resolved.is_dir()
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant package intake is not enabled.",
        ) from exc
    if not usable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant package intake is not enabled.",
        )
    return resolved


def _get_service(request: Request) -> TenantOnboardingService:
    service = getattr(request.app.state, "onboarding_service", None)
    if not isinstance(service, TenantOnboardingService):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred",
        )
    return service


def _config_service(request: Request) -> ConfigurationService | None:
    service = getattr(request.app.state, "config_service", None)
    if not isinstance(service, ConfigurationService):
        return None
    return service


def _correlation_id(request: Request) -> UUID:
    state_value = getattr(request.state, "correlation_id", None)
    if isinstance(state_value, UUID):
        return state_value
    try:
        return current_correlation_id()
    except LookupError:
        return uuid4()


def _item_body(item: TenantListItem) -> dict[str, str | int]:
    return {
        "slug": item.slug,
        "display_name": item.display_name,
        "status": item.status,
        "config_version": item.config_version,
    }


def _tool_checkboxes(name: str) -> str:
    boxes = []
    for tool in sorted(str(item) for item in KNOWN_TOOLS):
        label = escape(tool, quote=True)
        boxes.append(
            f'<label><input type="checkbox" name="{escape(name, quote=True)}" value="{label}"> {label}</label>'
        )
    return "\n        ".join(boxes)


def _render_list(
    request: Request, items: tuple[TenantListItem, ...], *, message: str
) -> str:
    rows = []
    for item in items:
        slug = escape(item.slug, quote=True)
        rows.append(
            "<tr>"
            f"<td>{slug}</td>"
            f"<td>{escape(item.display_name, quote=True)}</td>"
            f"<td>{escape(item.status, quote=True)}</td>"
            f"<td>{escape(str(item.config_version), quote=True)}</td>"
            f'<td><a href="/admin/instituciones/{slug}/chat">Probar</a></td>'
            "</tr>"
        )
    note = f"<p>{message}</p>" if message else ""
    return Template(_LIST_TEMPLATE.read_text(encoding="utf-8")).safe_substitute(
        rows="".join(rows),
        tool_checks=_tool_checkboxes("enabled_tools"),
        capability_checks=_tool_checkboxes("mcp_capabilities"),
        message=note,
    )


def _render_chat(
    request: Request,
    slug: str,
    *,
    history: tuple[dict[str, str], ...],
    error: str,
) -> str:
    packages = getattr(request.app.state, "tenant_packages_dir", None)
    name = display_name_for(packages if isinstance(packages, Path) else None, slug)
    bubbles = []
    for item in history:
        role = "user" if item.get("role") == "user" else "bot"
        bubbles.append(
            f'<div class="bubble {role}">{escape(item.get("text") or "", quote=True)}</div>'
        )
    encoded = escape(json.dumps(list(history)), quote=True)
    error_block = f'<p class="error">{error}</p>' if error else ""
    return Template(_CHAT_TEMPLATE.read_text(encoding="utf-8")).safe_substitute(
        display_name=escape(name, quote=True),
        slug=escape(slug, quote=True),
        bubbles="".join(bubbles),
        history=encoded,
        error=error_block,
    )


def _parse_history(raw: str) -> tuple[dict[str, str], ...]:
    if not raw.strip():
        return ()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(data, list):
        return ()
    items: list[dict[str, str]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        text = entry.get("text")
        if role not in {"user", "bot"} or not isinstance(text, str):
            continue
        items.append({"role": role, "text": text[:2000]})
        if len(items) >= _HISTORY_PAIRS * 2:
            break
    return tuple(items)


def _append_pair(
    history: tuple[dict[str, str], ...], *, user: str, bot: str
) -> tuple[dict[str, str], ...]:
    combined = list(history) + [
        {"role": "user", "text": user[:2000]},
        {"role": "bot", "text": bot[:2000]},
    ]
    return tuple(combined[-(_HISTORY_PAIRS * 2) :])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Resource not found",
    )


def _status_for(exc: OnboardingError) -> int:
    if exc.code in {"forbidden", "lab_unavailable"}:
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_400_BAD_REQUEST

