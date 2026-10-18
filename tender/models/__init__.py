"""Tender tables. Importing this package registers them on core's Base.metadata."""

from tender.models.library import (
    CorrectionCase,
    ModelAssumption,
    OAuthClient,
    OAuthCode,
    PublicationHold,
    WatchlistEntry,
)
from tender.models.review import ReviewToken, TenderReviewSnapshot
from tender.models.tender import (
    DOCUMENT_ROLES,
    TENDER_STATUSES,
    TENDER_TYPES,
    VERSION_KINDS,
    Tender,
    TenderFieldDef,
    TenderVersion,
    TenderVersionDocument,
)

__all__ = [
    "CorrectionCase",
    "ModelAssumption",
    "OAuthClient",
    "OAuthCode",
    "PublicationHold",
    "WatchlistEntry",
    "DOCUMENT_ROLES",
    "TENDER_STATUSES",
    "TENDER_TYPES",
    "VERSION_KINDS",
    "ReviewToken",
    "Tender",
    "TenderFieldDef",
    "TenderReviewSnapshot",
    "TenderVersion",
    "TenderVersionDocument",
]
