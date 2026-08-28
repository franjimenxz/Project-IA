from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from ia_mcp.observability.propagation import inject, start_span
from ia_mcp.observability.semconv import SPAN_CHANNEL_SEND


@dataclass(frozen=True, slots=True)
class OutboundDelivery:
    tenant_id: UUID
    tenant_slug: str
    correlation_id: UUID
    config_version: int
    run_id: UUID | None
    kind: str
    text: str
    source_ids: tuple[str, ...]
    external_message_id: str


class SimulatedTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_slug: str
    kind: str
    text: str
    source_ids: tuple[str, ...]
    correlation_id: UUID
    config_version: int
    run_id: UUID | None


class ChannelOutbox:
    def __init__(self) -> None:
        self._items: dict[tuple[UUID, str], OutboundDelivery] = {}
        self._carriers: dict[tuple[UUID, str], dict[str, str]] = {}

    async def put(self, delivery: OutboundDelivery) -> OutboundDelivery:
        key = (delivery.tenant_id, delivery.external_message_id)
        existing = self._items.get(key)
        if existing is not None:
            return existing
        attributes: dict[str, object] = {"status": "ok"}
        if delivery.run_id is not None:
            attributes["run_id"] = str(delivery.run_id)
        with start_span(SPAN_CHANNEL_SEND, attributes=attributes):
            carrier: dict[str, str] = {}
            inject(carrier)
            self._items[key] = delivery
            self._carriers[key] = carrier
            return delivery

    def carrier_for(self, delivery: OutboundDelivery) -> Mapping[str, str]:
        return self._carriers.get(
            (delivery.tenant_id, delivery.external_message_id), {}
        )

    def list(self) -> tuple[OutboundDelivery, ...]:
        return tuple(self._items.values())
