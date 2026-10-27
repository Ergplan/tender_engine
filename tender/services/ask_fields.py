"""Which field a question is about, if any (Stage 7, Block 5 b). Deterministic: the
question's words against each field's label and path words, with a few domain aliases;
a field is matched when its label is covered and no other field comes as close. A question
that maps to no field, or to two fields equally, is answered from retrieved pages instead,
which is the honest fallback: a wrong field answers the wrong question with confidence."""

import re
from dataclasses import dataclass

from core.schemas.model import ExtractionSchema, FieldDef

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "of", "for", "in", "on", "at", "to",
    "by", "and", "or", "what", "which", "when", "how", "much", "many", "does", "do", "did",
    "this", "that", "tender", "tenders", "rfs", "rfp", "under", "with", "per", "its", "it",
    "there", "any", "please", "tell", "me", "about", "give", "show", "value",
    "amount", "as", "from", "into", "will", "shall", "should", "would", "can", "has", "have",
}  # fmt: skip
# A word of the question that stands for words a label uses.
ALIASES: dict[str, tuple[str, ...]] = {
    "deadline": ("last", "date", "deadline", "submission"),
    "last": ("deadline",),
    "closing": ("deadline", "submission"),
    "due": ("deadline", "submission"),
    "emd": ("earnest", "money", "deposit", "emd"),
    "earnest": ("emd",),
    "pbg": ("performance", "bank", "guarantee", "pbg"),
    "guarantee": ("pbg", "guarantee"),
    "capacity": ("capacity", "mw"),
    "size": ("capacity",),
    "tariff": ("tariff", "ceiling", "price"),
    "price": ("tariff", "price"),
    "ceiling": ("ceiling", "tariff"),
    "tenure": ("tenure", "term", "years"),
    "term": ("tenure", "term"),
    "prebid": ("pre", "bid", "meeting"),
    "pre-bid": ("pre", "bid", "meeting"),
    "opening": ("opening",),
    "commissioning": ("commissioning", "scod"),
    "scod": ("commissioning", "scod"),
    "penalty": ("penalty", "penalties", "damages"),
    "penalties": ("penalty", "penalties"),
    "agency": ("agency", "issuer", "issuing"),
    "issuer": ("agency", "issuing"),
    "who": ("agency", "issuing", "buyer", "procurer"),
    "buyer": ("buyer", "procurer", "offtaker"),
    "offtaker": ("buyer", "procurer", "offtaker"),
    "validity": ("validity", "valid"),
    "cuf": ("cuf", "utilisation", "utilization"),
    "degradation": ("degradation",),
    "storage": ("storage", "ess", "bess"),
    "battery": ("storage", "bess"),
    "connectivity": ("connectivity", "ists", "grid"),
    "net": ("net", "worth"),
    "turnover": ("turnover",),
}

_WORD = re.compile(r"[a-z0-9][a-z0-9\-]*")


def words(text: str) -> list[str]:
    out = []
    for raw in _WORD.findall(text.lower()):
        token = raw.strip("-")
        if not token or token in STOPWORDS:
            continue
        out.append(_singular(token))
    return out


def _singular(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def question_words(question: str) -> set[str]:
    base = set(words(question))
    expanded = set(base)
    for word in base:
        expanded.update(ALIASES.get(word, ()))
    return {_singular(w) for w in expanded}


@dataclass(frozen=True)
class FieldMatch:
    field: FieldDef
    score: float
    matched: tuple[str, ...]


def label_words(field: FieldDef) -> set[str]:
    leaf = field.path.rsplit(".", 1)[-1].replace("_", " ")
    out = set(words(field.label)) | set(words(leaf))
    return {w for w in out if w not in {"inr", "no", "number"}} or out


def map_question(
    question: str, schema: ExtractionSchema, *, threshold: float = 0.75, margin: float = 0.15
) -> FieldMatch | None:
    """The field the question is about, or None (ask the pages). A field matches when at
    least `threshold` of its label words appear in the question; ties within `margin` are
    ambiguous and answer None."""
    asked = question_words(question)
    if not asked:
        return None
    own = set(words(question))
    labels: dict[str, set[str]] = {}
    coverages: dict[str, float] = {}
    scored: list[FieldMatch] = []
    for field in schema.fields:
        label = label_words(field)
        if not label:
            continue
        hit = asked & label
        coverage = len(hit) / len(label)
        labels[field.path] = label
        coverages[field.path] = coverage
        if coverage < threshold or (len(label) == 1 and len(hit) == 0):
            continue
        # Coverage first; among equal coverage the label with more words matched wins
        # (`bid submission deadline` over `bid opening` for "bid submission deadline").
        score = coverage + 0.01 * len(hit)
        scored.append(FieldMatch(field, round(score, 4), tuple(sorted(hit))))
    if not scored:
        return None
    scored.sort(key=lambda m: (-m.score, m.field.path))
    best = scored[0]
    # Two fields fit the words about equally: a sub-field of the same group with the same
    # leaf words (`emd_per_mw_inr` and `emd_structured`) is the common case.
    if (
        len(scored) > 1
        and scored[1].score > best.score - margin
        and scored[1].field.path != best.field.path
        and len(best.matched) <= len(scored[1].matched)
    ):
        return None
    # The question's own words (before the aliases) all sit in another field's label too,
    # and that field fits nearly as well: "deadline" alone names the query deadline no
    # more than the bid submission deadline, so the pages answer.
    own_hit = own & labels[best.field.path]
    for path, label in labels.items():
        if path == best.field.path or coverages[path] <= coverages[best.field.path] - margin:
            continue
        if own_hit <= label:
            return None
    return best
