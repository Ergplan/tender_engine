from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MeOut(BaseModel):
    kind: Literal["user", "api_key", "review_token", "admin_token"]
    name: str
    role: str
    tenant_id: str
    read_tenants: list[str]
    scopes: list[str]
    user_id: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    role: str
    status: str
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    role: Literal["reviewer", "approver", "admin"] = "reviewer"


class UserPatch(BaseModel):
    role: Literal["reviewer", "approver", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str
    scopes: list[str]
    rate_limit_per_min: int
    daily_cap: int
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    created_by: str


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[Literal["read", "model", "write", "review:mint"]] = ["read"]
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=10000)
    daily_cap: int | None = Field(default=None, ge=1, le=10_000_000)


class ApiKeyCreated(BaseModel):
    """The key itself, shown once."""

    key: ApiKeyOut
    secret: str


class ReviewTokenMint(BaseModel):
    tender: str = Field(description="The tender's id or slug")
    reviewer_name: str = Field(min_length=1, max_length=200)


class UsageByTool(BaseModel):
    tool: str
    calls: int
    errors: int


class UsageByKey(BaseModel):
    api_key_id: str | None
    name: str | None
    calls: int


class UsageOut(BaseModel):
    days: int
    calls: int
    by_tool: list[UsageByTool]
    by_key: list[UsageByKey]
