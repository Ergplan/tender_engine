"""Request dependencies: settings, db session, tenant. Reviewer arrives in Stage 3."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from core.config import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def get_tenant_id(settings: Annotated[Settings, Depends(get_settings)]) -> str:
    """Phase 1 resolves every request to the single configured tenant."""
    return settings.tenant_id


SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[str, Depends(get_tenant_id)]
