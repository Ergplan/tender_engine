from datetime import datetime

from pydantic import BaseModel


class AwardOut(BaseModel):
    """One imported result publication: its identity and provenance. The `dataset_*`
    fields are the dataset's own labels for the publication (which agency, which
    reference, which kind), for listing and matching; they are not reviewed facts. What
    the publication says is in its review state (candidates) and, once approved, in its
    results (facts, `/awards/{id}/results`)."""

    id: str
    source_id: str
    source_name: str
    source_url: str
    source_sha256: str
    dataset: str
    dataset_procurer: str
    dataset_reference: str
    dataset_result_kind: str
    dataset_verification: str
    row_count: int
    document_id: str
    tender_id: str | None
    tender_link_basis: str | None
    tender_link_page: int | None
    status: str
    created_at: datetime
