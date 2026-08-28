from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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

    async def put(self, delivery: OutboundDelivery) -> OutboundDelivery:
        key = (delivery.tenant_id, delivery.external_message_id)
        existing = self._items.get(key)
        if existing is not None:
            return existing
        self._items[key] = delivery
        return delivery

    def list(self) -> tuple[OutboundDelivery, ...]:
        return tuple(self._items.values())
