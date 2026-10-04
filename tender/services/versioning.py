"""Which field groups of a tender version are extracted from which of its documents.

The original version is read in full: each document is given the groups whose roles
include the document's role. A later version (corrigendum, amendment, clarification) is
read only where it touches the tender: a group is extracted from one of its documents
only when the document mentions one of the group's routing keywords. Fields a later
version does not mention keep the canonical facts of the earlier versions untouched.
"""

from core.schemas import ExtractionSchema
from tender.services.packs import CompiledType

CHANGE_ROLES = ("amendment", "clarification")
SUMMARY_SECTION = "summary"


def groups_for_role(compiled: CompiledType, role: str) -> list[str]:
    """Groups a document of this role may be read for. An amendment or clarification can
    change any section except the summary, which is written from the base document."""
    if role in CHANGE_ROLES:
        return [s.name for s in compiled.sections if s.name != SUMMARY_SECTION]
    return [section.name for section in compiled.sections if role in section.roles]


def touched_groups(schema: ExtractionSchema, groups: list[str], page_texts: list[str]) -> list[str]:
    """Of the given groups, those whose routing keywords occur in the document text."""
    text = "\n".join(page_texts).lower()
    touched = []
    for group in schema.groups:
        keywords = [keyword.lower() for keyword in group.routing.keywords if keyword.strip()]
        if group.name in groups and any(keyword in text for keyword in keywords):
            touched.append(group.name)
    return touched


def plan_groups(
    compiled: CompiledType, *, version_no: int, role: str, page_texts: list[str]
) -> list[str]:
    """The groups to extract from one document of a tender version."""
    groups = groups_for_role(compiled, role)
    if version_no == 1:
        return groups
    return touched_groups(compiled.schema, groups, page_texts)
