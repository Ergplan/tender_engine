"""Evidence resolution: find a quoted passage on a page.

Standalone: this package imports nothing from the rest of core, no ORM and no settings.
Input is a quote and a page (its text and one box per character); output is a Match with
character offsets, a bounding box, a score and the method that found it, or a Miss with
the best score any method reached.
"""

from core.evidence.resolver import (
    Located,
    Match,
    Miss,
    PageText,
    locate,
    normalise,
    resolve,
    resolve_pair,
)

__all__ = [
    "Located",
    "Match",
    "Miss",
    "PageText",
    "locate",
    "normalise",
    "resolve",
    "resolve_pair",
]
