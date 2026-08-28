from pydantic import BaseModel, ConfigDict, Field


class SimulatedMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_message_id: str = Field(min_length=1)
    external_user_id: str = Field(min_length=1)
    text: str


class SimulatedMessageAck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_slug: str
