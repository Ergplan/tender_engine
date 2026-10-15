"""Review rounds opened by a version.

A reviewed tender that a later version reaches is not reviewed from scratch: once that
version's runs are validated, a round opens for the reviewer who completed the last
review — a new link scoped to the fields the version touched (`ReviewToken.from_version`,
read by `tender.services.review.tender_review`), the earlier decisions carrying forward
with their provenance. One live link per tender: nothing opens while a review or a round
is still open. The round is recorded in the audit log; the link itself is handed to the
reviewer by the operator (`scripts.review_token list`), never written anywhere else.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import ExtractionRun
from core.models.extraction import RECORD_MODES
from core.services import audit
from tender.services.tenders import OBJECT_TYPE, TenderService
from tender.services.tokens import TokenService

log = logging.getLogger("tender.rounds")
ACTOR = "rounds"


class RoundOpener:
    def __init__(self, tenders: TenderService, tokens: TokenService, tenant_id: str) -> None:
        self._tenders = tenders
        self._tokens = tokens
        self._tenant_id = tenant_id

    def after_validation(self, session: Session, extraction_run_id: str) -> None:
        """Called by the worker when a run has been validated: a page run on a later
        version of a reviewed tender, with no other reading of that tender under way,
        opens a round from that version."""
        run = session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.id == extraction_run_id, ExtractionRun.tenant_id == self._tenant_id
            )
        )
        if (
            run is None
            or run.object_type != OBJECT_TYPE
            or run.mode in RECORD_MODES
            or run.object_version <= 1
        ):
            return
        tender = self._tenders.get(session, run.object_id)
        if tender.status != "reviewed":
            return
        under_way = session.scalar(
            select(ExtractionRun.id)
            .where(
                ExtractionRun.tenant_id == self._tenant_id,
                ExtractionRun.object_type == OBJECT_TYPE,
                ExtractionRun.object_id == tender.id,
                ExtractionRun.mode.notin_(RECORD_MODES),
                ExtractionRun.status.in_(("queued", "running", "extracted")),
            )
            .limit(1)
        )
        if under_way is not None:
            return
        token = self._tokens.open_round(
            session, tender, from_version=run.object_version, created_by=ACTOR
        )
        if token is None:
            return
        tender.status = "in_review"
        audit.record(
            session,
            tenant_id=self._tenant_id,
            actor=ACTOR,
            action="open_round",
            table_name="tender",
            row_id=tender.id,
            before={"status": "reviewed"},
            after={
                "status": "in_review",
                "round_no": token.round_no,
                "from_version": token.from_version,
                "review_token_id": token.id,
                "reviewer_name": token.reviewer_name,
            },
        )
        session.commit()
        log.info(
            "round %s opened on %s from v%s for %s",
            token.round_no,
            tender.slug or tender.id,
            token.from_version,
            token.reviewer_name,
        )
