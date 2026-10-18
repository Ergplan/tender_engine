"""The published view, the changelog and the comparison (Stage 5C): the service models
are the response models, so the shape a client sees is the shape the service makes."""

from tender.services.changelog import Changelog as ChangelogOut
from tender.services.compare import Comparison as CompareOut
from tender.services.published import PublishedTender as PublishedOut

__all__ = ["ChangelogOut", "CompareOut", "PublishedOut"]
