from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from ia_mcp.contracts.errors import ToolError

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class ToolResult[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    value: T | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def value_xor_error_matches_ok(self) -> Self:
        if self.ok:
            if self.value is None or self.error is not None:
                raise ValueError("ok results require value and forbid error")
        elif self.error is None or self.value is not None:
            raise ValueError("error results require error and forbid value")
        return self
