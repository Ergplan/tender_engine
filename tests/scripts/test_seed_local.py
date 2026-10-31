"""The local seed (`make local`): an admin who can sign in, the demo tender once, and a
refusal anywhere but localhost."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import Settings
from core.db import set_tenant
from core.models.identity import AppUser
from core.services.identity import IdentityService
from scripts import seed_local
from tender.models import ReviewToken, Tender


def local(settings: Settings) -> Settings:
    return settings.model_copy(update={"public_base_url": "http://localhost:8080"})


@pytest.mark.parametrize(
    "url", ["https://34-131-65-108.sslip.io", "https://34.131.65.108", "http://tenders.example.com"]
)
def test_refuses_anything_but_localhost(settings: Settings, url: str, db: Session) -> None:
    assert seed_local.run(settings.model_copy(update={"public_base_url": url}), demo=True) == 2
    set_tenant(db, settings.tenant_id)
    assert db.scalar(select(func.count()).select_from(AppUser)) == 0


def test_admin_signs_in_and_keeps_a_changed_password(
    settings: Settings, db: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed_local.run(local(settings), demo=False) == 0
    assert "admin-local-dev" in capsys.readouterr().out
    identity = IdentityService(settings)
    user = identity.login_with_password(db, "admin", seed_local.LOCAL_PASSWORD)
    assert user is not None and user.role == "admin"

    identity.set_password(db, "admin", "a-password-the-dev-chose", created_by="test")
    assert seed_local.run(local(settings), demo=False) == 0
    assert "admin exists" in capsys.readouterr().out
    assert identity.login_with_password(db, "admin", "a-password-the-dev-chose") is not None


def test_demo_tender_is_seeded_once_without_a_model(
    settings: Settings, db: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed_local.run(local(settings), demo=True) == 0
    assert "/review/e2e-review-token-" in capsys.readouterr().out
    assert seed_local.run(local(settings), demo=True) == 0
    assert "already present" in capsys.readouterr().out
    set_tenant(db, settings.tenant_id)
    assert db.scalar(select(func.count()).select_from(Tender)) == 1
    assert db.scalar(select(func.count()).select_from(ReviewToken)) == 2
