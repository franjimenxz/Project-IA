from typing import Protocol

from ia_mcp.contracts.appointments import (
    Appointment,
    AppointmentCancelRequest,
    AppointmentConfirmRequest,
    AppointmentCreateRequest,
    AppointmentGetRequest,
    AppointmentRescheduleRequest,
    AppointmentSearchRequest,
    AppointmentSlot,
)
from ia_mcp.contracts.common import ToolResult
from ia_mcp.tenancy.models import TenantContext


class AppointmentCapability(Protocol):
    async def search(
        self,
        tenant: TenantContext,
        request: AppointmentSearchRequest,
    ) -> ToolResult[list[AppointmentSlot]]: ...

    async def get(
        self,
        tenant: TenantContext,
        request: AppointmentGetRequest,
    ) -> ToolResult[Appointment]: ...

    async def create(
        self,
        tenant: TenantContext,
        request: AppointmentCreateRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]: ...

    async def cancel(
        self,
        tenant: TenantContext,
        request: AppointmentCancelRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]: ...

    async def reschedule(
        self,
        tenant: TenantContext,
        request: AppointmentRescheduleRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]: ...

    async def confirm(
        self,
        tenant: TenantContext,
        request: AppointmentConfirmRequest,
        idempotency_key: str,
    ) -> ToolResult[Appointment]: ...
