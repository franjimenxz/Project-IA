from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import ValidationError

from ia_mcp.contracts.appointments import (
    AppointmentCancelRequest,
    AppointmentConfirmRequest,
    AppointmentCreateRequest,
    AppointmentGetRequest,
    AppointmentRescheduleRequest,
    AppointmentSearchRequest,
)
from ia_mcp.contracts.common import ToolResult
from ia_mcp.contracts.errors import ToolError, ToolErrorCode
from ia_mcp.mcp.capabilities.appointments import AppointmentCapability
from ia_mcp.mcp.registry import KNOWN_TOOLS, ForbiddenTool, authorize
from ia_mcp.observability.propagation import (
    bind_telemetry,
    extract,
    inject,
    reset_telemetry,
    start_span,
)
from ia_mcp.observability.semconv import SPAN_MCP_RESOLVE, SPAN_TOOL_EXECUTE
from ia_mcp.tenancy.models import TenantContext

_FORBIDDEN = ToolError(
    code=ToolErrorCode.FORBIDDEN,
    retryable=False,
    safe_message="Action is not allowed.",
)
_INVALID = ToolError(
    code=ToolErrorCode.VALIDATION_ERROR,
    retryable=False,
    safe_message="The request is invalid.",
)


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class McpTarget:
    server_id: str
    allowed_tools: frozenset[str]
    endpoint: str = ""
    auth_reference: str = ""


class McpResolver(Protocol):
    async def resolve(self, tenant: TenantContext, capability: str) -> McpTarget: ...


class McpTransportClient(Protocol):
    async def call_tool(
        self,
        tenant: TenantContext,
        target: McpTarget,
        name: str,
        arguments: Mapping[str, Any],
    ) -> ToolResult[Any]: ...


@dataclass(frozen=True, slots=True)
class ToolAuditEvent:
    run_id: UUID
    tenant_id: UUID
    tool: str
    allowed: bool
    error_code: ToolErrorCode | None = None
    mcp_server_id: str | None = None


class HostAllowlist:
    """Network allowlist for resolved MCP endpoints.

    A resolved target is data: the record may be stale, misconfigured or
    tenant-controlled. Once an allowlist is configured nothing outside it is
    reachable, plaintext transport is refused and a missing endpoint fails
    closed instead of defaulting to "no restriction".
    """

    def __init__(self, hosts: Iterable[str]) -> None:
        self._hosts = frozenset(
            host.strip().lower() for host in hosts if host and host.strip()
        )

    def permits(self, endpoint: str) -> bool:
        if not endpoint:
            return False
        parsed = urlsplit(endpoint)
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        # Bare host entries remain https-only. http requires an explicit
        # "http://host" pair so LAN fixtures can be listed without opening
        # plaintext to every https-allowlisted production host.
        if parsed.scheme == "https":
            return host in self._hosts or f"https://{host}" in self._hosts
        if parsed.scheme == "http":
            return f"http://{host}" in self._hosts
        return False


class ToolRegistry:
    """Wraps registry.authorize with construction-time allowlists."""

    def __init__(
        self,
        *,
        server: Iterable[str],
        tenant: Iterable[str],
        skill: Iterable[str],
    ) -> None:
        self._server = frozenset(server)
        self._tenant = frozenset(tenant)
        self._skill = frozenset(skill)

    def authorize(self, tool: str) -> str:
        return authorize(
            tool,
            server=self._server,
            tenant=self._tenant,
            skill=self._skill,
        )


class ToolExecutor:
    def __init__(
        self,
        *,
        server: Iterable[str],
        tenant: Iterable[str],
        skill: Iterable[str],
        capability: AppointmentCapability,
        resolver: McpResolver | None = None,
        audit_hook: Callable[[ToolAuditEvent], None] | None = None,
        allowed_hosts: Iterable[str] | None = None,
        transport: McpTransportClient | None = None,
    ) -> None:
        if allowed_hosts is not None and resolver is None:
            # Only a resolved target carries an endpoint. Accepting the allowlist
            # here would advertise a network restriction that never runs, so the
            # wiring error fails closed instead of dispatching every call.
            raise ValueError(
                "allowed_hosts requires a resolver: without one there is no "
                "endpoint to validate and the allowlist would never apply"
            )
        if transport is not None and (resolver is None or allowed_hosts is None):
            # Generic invoke is network I/O. Without resolver + allowlist the
            # client would run against an unrestricted or missing endpoint.
            raise ValueError(
                "transport requires a resolver and allowed_hosts: generic "
                "invoke must fail closed before any network call"
            )
        self._registry = ToolRegistry(server=server, tenant=tenant, skill=skill)
        self._capability = capability
        self._resolver = resolver
        self._audit_hook = audit_hook
        self._hosts = None if allowed_hosts is None else HostAllowlist(allowed_hosts)
        self._transport = transport

    async def execute(
        self,
        tenant: TenantContext,
        run_id: UUID,
        call: ToolCall,
        carrier: MutableMapping[str, str] | None = None,
    ) -> ToolResult[Any]:
        token = None
        if carrier:
            token = bind_telemetry(extract(carrier))
        try:
            with start_span(
                SPAN_TOOL_EXECUTE,
                attributes={
                    "tool_name": call.name,
                    "run_id": str(run_id),
                    "tenant_id": str(tenant.tenant_id),
                },
            ):
                result = await self._execute_authorized(tenant, run_id, call)
                if carrier is not None:
                    inject(carrier)
                return result
        finally:
            if token is not None:
                reset_telemetry(token)

    async def _execute_authorized(
        self,
        tenant: TenantContext,
        run_id: UUID,
        call: ToolCall,
    ) -> ToolResult[Any]:
        try:
            self._registry.authorize(call.name)
        except ForbiddenTool:
            self._audit(
                ToolAuditEvent(
                    run_id=run_id,
                    tenant_id=tenant.tenant_id,
                    tool=call.name,
                    allowed=False,
                    error_code=ToolErrorCode.FORBIDDEN,
                )
            )
            return ToolResult[Any](ok=False, error=_FORBIDDEN)

        target: McpTarget | None = None
        if self._resolver is not None:
            capability_name = call.name.split(".", 1)[0]
            with start_span(SPAN_MCP_RESOLVE) as span:
                target = await self._resolver.resolve(tenant, capability_name)
                span.set_attribute("mcp_server_id", target.server_id)
            tool_denied = call.name not in target.allowed_tools
            if self._transport is not None:
                host_denied = (
                    self._hosts is None or not self._hosts.permits(target.endpoint)
                )
            else:
                host_denied = (
                    self._hosts is not None and not self._hosts.permits(target.endpoint)
                )
            denied = tool_denied or host_denied
            if denied:
                self._audit(
                    ToolAuditEvent(
                        run_id=run_id,
                        tenant_id=tenant.tenant_id,
                        tool=call.name,
                        allowed=False,
                        error_code=ToolErrorCode.FORBIDDEN,
                        mcp_server_id=target.server_id,
                    )
                )
                return ToolResult[Any](ok=False, error=_FORBIDDEN)

        result = await self._dispatch(tenant, call, target)
        self._audit(
            ToolAuditEvent(
                run_id=run_id,
                tenant_id=tenant.tenant_id,
                tool=call.name,
                allowed=True,
                error_code=None
                if result.ok or result.error is None
                else result.error.code,
                mcp_server_id=None if target is None else target.server_id,
            )
        )
        return result

    def _audit(self, event: ToolAuditEvent) -> None:
        if self._audit_hook is not None:
            self._audit_hook(event)

    async def _dispatch(
        self,
        tenant: TenantContext,
        call: ToolCall,
        target: McpTarget | None,
    ) -> ToolResult[Any]:
        if call.name in KNOWN_TOOLS:
            return await self._dispatch_capability(tenant, call)
        if self._transport is not None and target is not None:
            if self._hosts is None or not self._hosts.permits(target.endpoint):
                return ToolResult[Any](ok=False, error=_FORBIDDEN)
            return await self._transport.call_tool(
                tenant,
                target,
                call.name,
                dict(call.arguments),
            )
        return ToolResult[Any](ok=False, error=_FORBIDDEN)

    async def _dispatch_capability(
        self,
        tenant: TenantContext,
        call: ToolCall,
    ) -> ToolResult[Any]:
        payload = dict(call.arguments)
        try:
            if call.name == "appointments.search":
                request = AppointmentSearchRequest.model_validate(payload)
                return await self._capability.search(tenant, request)
            if call.name == "appointments.get":
                request_get = AppointmentGetRequest.model_validate(payload)
                return await self._capability.get(tenant, request_get)
            if call.name == "appointments.create":
                request_create = AppointmentCreateRequest.model_validate(payload)
                return await self._capability.create(
                    tenant,
                    request_create,
                    idempotency_key=self._require_idempotency_key(call),
                )
            if call.name == "appointments.cancel":
                request_cancel = AppointmentCancelRequest.model_validate(payload)
                return await self._capability.cancel(
                    tenant,
                    request_cancel,
                    idempotency_key=self._require_idempotency_key(call),
                )
            if call.name == "appointments.reschedule":
                request_reschedule = AppointmentRescheduleRequest.model_validate(
                    payload
                )
                return await self._capability.reschedule(
                    tenant,
                    request_reschedule,
                    idempotency_key=self._require_idempotency_key(call),
                )
            if call.name == "appointments.confirm":
                request_confirm = AppointmentConfirmRequest.model_validate(payload)
                return await self._capability.confirm(
                    tenant,
                    request_confirm,
                    idempotency_key=self._require_idempotency_key(call),
                )
        except ValidationError:
            return ToolResult[Any](ok=False, error=_INVALID)
        except _MissingIdempotency:
            return ToolResult[Any](ok=False, error=_INVALID)
        return ToolResult[Any](ok=False, error=_FORBIDDEN)

    @staticmethod
    def _require_idempotency_key(call: ToolCall) -> str:
        key = call.idempotency_key
        if key is None:
            raise _MissingIdempotency
        return key


class _MissingIdempotency(Exception):
    pass
