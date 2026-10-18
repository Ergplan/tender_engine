"""The library tier's request and response bodies (Stage 5D). The response models are the
service's own, re-exported, so the API says exactly what the service says."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tender.models.library import CORRECTION_STATUSES as _CORRECTION_STATUSES
from tender.services.library import (
    FixedParameter,
    Match,
    MatchCandidate,
    ModelResult,
    NoMatch,
    SearchResult,
    TenderSearchHit,
    WatchedTender,
)

__all__ = [
    "AssumptionsIn",
    "AssumptionsOut",
    "CorrectionIn",
    "CorrectionOut",
    "CorrectionResolve",
    "FixedParameter",
    "HoldIn",
    "HoldOut",
    "Match",
    "MatchCandidate",
    "MatchOut",
    "ModelIn",
    "ModelResult",
    "NoMatch",
    "SearchResult",
    "TenderSearchHit",
    "SignupIn",
    "WatchlistIn",
    "WatchedTender",
]

CORRECTION_STATUSES = _CORRECTION_STATUSES


class ModelIn(BaseModel):
    model_type: str = "power_project_finance"
    assumptions: dict[str, Any] | None = None


class AssumptionsIn(BaseModel):
    model_type: str = "power_project_finance"
    assumptions: dict[str, Any]


class AssumptionsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tender_id: str
    model_type: str
    assumptions: dict[str, Any]
    created_at: datetime


class WatchlistIn(BaseModel):
    tender_id: str


class CorrectionIn(BaseModel):
    tender_id: str
    field_path: str = Field(min_length=3, max_length=200)
    claimed_error: str = Field(min_length=1, max_length=4000)
    reasoning: str = Field(min_length=1, max_length=8000)
    claimant_email: str | None = Field(default=None, max_length=320)


class CorrectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tender_id: str
    field_path: str
    claimed_error: str
    reasoning: str
    claimant_tenant_id: str | None
    claimant_email: str | None
    status: str
    resolution: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime


class CorrectionResolve(BaseModel):
    accepted: bool
    resolution: str = Field(min_length=1, max_length=4000)


class HoldIn(BaseModel):
    tender_id: str
    kind: Literal["takedown", "correction"] = "takedown"
    reason: str = Field(min_length=1, max_length=4000)
    # When the request arrived, as the operator states it.
    requested_at: datetime | None = None


class HoldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tender_id: str
    kind: str
    reason: str
    requested_by: str
    requested_at: datetime | None
    lifted_at: datetime | None
    lifted_by: str | None
    created_at: datetime


class SignupIn(BaseModel):
    """A programmatic free sign-up: the provider's code, exchanged as the callback would."""

    code: str = Field(min_length=1)


MatchOut = Match | NoMatch
