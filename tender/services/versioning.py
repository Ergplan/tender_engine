"""Which field groups of a tender version are extracted from which of its documents.

The original version is read in full: each document is given the groups whose roles
include the document's role. A later version (corrigendum, amendment, clarification) is
read only where it touches the tender: a group is extracted from one of its documents
only when the document mentions one of the group's routing keywords. Fields a later
version does not mention keep the canonical facts of the earlier versions untouched.
"""

from collections.abc import Iterable

from core.schemas import ExtractionSchema
from tender.services.packs import CompiledType

CHANGE_ROLES = ("amendment", "clarification")
SUMMARY_SECTION = "summary"
NOTICE_ROLE = "nit"
BASE_ROLES = ("rfs", "contractual")


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
    compiled: CompiledType,
    *,
    version_no: int,
    role: str,
    page_texts: list[str],
    version_roles: Iterable[str] = (),
) -> list[str]:
    """The groups to extract from one document of a tender version. `version_roles` are
    the roles of all documents of that version.

    The summary is written from the tender's base documents. A published notice is read
    for it only when it is all the original version has (a tender known only by its
    notice); a notice beside an RfS or contractual volume, or attached to a later version,
    is not."""
    groups = groups_for_role(compiled, role)
    if role == NOTICE_ROLE and (version_no > 1 or set(version_roles) & set(BASE_ROLES)):
        groups = [name for name in groups if name != SUMMARY_SECTION]
    if version_no == 1:
        return groups
    return touched_groups(compiled.schema, groups, page_texts)
