"""Tender tables. Importing this package registers them on core's Base.metadata."""

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
    "DOCUMENT_ROLES",
    "TENDER_STATUSES",
    "TENDER_TYPES",
    "VERSION_KINDS",
    "Tender",
    "TenderFieldDef",
    "TenderVersion",
    "TenderVersionDocument",
]
