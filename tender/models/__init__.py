"""Tender tables. Importing this package registers them on core's Base.metadata."""

from tender.models.award import AWARD_STATUSES, LINK_BASES, Award
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
    TYPE_SOURCES,
    TYPE_STATES,
    VERSION_KINDS,
    Tender,
    TenderFieldDef,
    TenderVersion,
    TenderVersionDocument,
)

__all__ = [
    "AWARD_STATUSES",
    "Award",
    "LINK_BASES",
    "CorrectionCase",
    "ModelAssumption",
    "OAuthClient",
    "OAuthCode",
    "PublicationHold",
    "WatchlistEntry",
    "DOCUMENT_ROLES",
    "TENDER_STATUSES",
    "TENDER_TYPES",
    "TYPE_SOURCES",
    "TYPE_STATES",
    "VERSION_KINDS",
    "ReviewToken",
    "Tender",
    "TenderFieldDef",
    "TenderReviewSnapshot",
    "TenderVersion",
    "TenderVersionDocument",
]
