"""SQLAlchemy tables. Importing this package registers every model on Base.metadata."""

from core.models.base import Base
from core.models.document import Document, Page, Section
from core.models.extraction import Candidate, EvidenceSpan, ExtractionRun, ValidationResult
from core.models.identity import ApiKey, AppUser, LoginSession, UsageRecord
from core.models.job import Job
from core.models.llm_call_log import LLMBatch, LLMCallLog
from core.models.retrieval import RetrievalChunk
from core.models.tenant import Tenant
from core.models.truth import Approval, AuditLog, CanonicalFact, Feedback
from core.models.webhook import WebhookDelivery, WebhookEndpoint

__all__ = [
    "ApiKey",
    "AppUser",
    "Approval",
    "AuditLog",
    "Base",
    "Candidate",
    "CanonicalFact",
    "Document",
    "EvidenceSpan",
    "ExtractionRun",
    "Feedback",
    "Job",
    "LLMBatch",
    "LLMCallLog",
    "LoginSession",
    "Page",
    "RetrievalChunk",
    "Section",
    "Tenant",
    "UsageRecord",
    "WebhookDelivery",
    "WebhookEndpoint",
    "ValidationResult",
]
