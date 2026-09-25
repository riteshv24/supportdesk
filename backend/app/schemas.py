from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["open", "in_progress", "resolved"]
Priority = Literal["low", "medium", "high", "urgent"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.lower()
        parts = value.split("@")
        if len(parts) != 2 or not parts[0] or "." not in parts[1] or " " in value:
            raise ValueError("Enter a valid email address")
        return value


class Register(Credentials):
    name: str = Field(min_length=1, max_length=80)
    workspace_name: str = Field(min_length=1, max_length=80)


class TicketCreate(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=10000)
    priority: Priority = "medium"
    assignee_id: int | None = None


class TicketPatch(StrictModel):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10000)
    status: Status | None = None
    priority: Priority | None = None
    assignee_id: int | None = None


class CommentCreate(StrictModel):
    body: str = Field(min_length=1, max_length=5000)


class MemberCreate(StrictModel):
    email: str = Field(min_length=3, max_length=254)
