"""SQLAlchemy tables. Importing this package registers every model on Base.metadata."""

from core.models.base import Base
from core.models.document import Document, Page, Section
from core.models.extraction import Candidate, EvidenceSpan, ExtractionRun, ValidationResult
from core.models.job import Job
from core.models.llm_call_log import LLMCallLog
from core.models.tenant import Tenant
from core.models.truth import Approval, AuditLog, CanonicalFact, Feedback

__all__ = [
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
    "LLMCallLog",
    "Page",
    "Section",
    "Tenant",
    "ValidationResult",
]
