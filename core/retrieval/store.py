"""The chunk store: Haystack's pgvector document store over the `retrieval_chunk` table that
migration 0023 made in the existing database, under the same row-level security as every
other table. The store opens its own connection (Haystack's, psycopg), so the tenant scope
is set on that connection the way `core.db.set_tenant` sets it on a session; a store serves
one tenant, and `ChunkStores` keeps one per tenant."""

import re
import threading
from typing import Any

from haystack import Document
from haystack.utils import Secret
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore

# Haystack's own keyword SQL and its row-to-Document reader, so the store's any-word query
# below returns exactly what the every-word query returns (pgvector-haystack 8).
from haystack_integrations.document_stores.pgvector.document_store import (  # type: ignore[attr-defined]
    KEYWORD_QUERY,
    _from_pg_to_haystack_documents,
)
from haystack_integrations.document_stores.pgvector.filters import (
    _convert_filters_to_where_clause_and_params,
)
from psycopg.sql import SQL, Composed, Identifier
from psycopg.sql import Literal as SQLLiteral

from core.config import Settings
from core.models.retrieval import EMBEDDING_DIMENSION

TABLE = "retrieval_chunk"
# Haystack's keyword SQL asks for every word of the question (`plainto_tsquery` joins the
# lexemes with AND), so a question with one word the page does not use finds nothing. When
# that finds nothing the store asks for any of the words (`to_tsquery` over the lexemes
# joined with OR), as long as a chunk holds at least `MIN_TERMS` of them: a chunk that
# shares one common word with the question is not an answer. `ts_rank_cd` ranks the chunk
# with the most of them first.
KEYWORD_ANY_QUERY = """SELECT {table_name}.*,
  ts_rank_cd(to_tsvector({language}, content), query) AS score
FROM {schema_name}.{table_name}, to_tsquery({language}, %s) query
WHERE to_tsvector({language}, content) @@ query
AND (SELECT count(*) FROM unnest(%s::text[]) AS term
     WHERE to_tsvector({language}, content) @@ plainto_tsquery({language}, term)) >= %s"""
MIN_TERMS = 2
_TERM = re.compile(r"[a-z0-9]+")
__all__ = [
    "EMBEDDING_DIMENSION",
    "TABLE",
    "ChunkStores",
    "TenantChunkStore",
    "or_terms",
    "psycopg_url",
    "terms_of",
]


def terms_of(question: str) -> list[str]:
    """The question's distinct words, lower case, in order."""
    seen: list[str] = []
    for term in _TERM.findall(question.lower()):
        if term not in seen:
            seen.append(term)
    return seen


def or_terms(question: str) -> str:
    """The question's words as a `to_tsquery` expression that matches any of them:
    "What PBG must the bidder furnish?" -> "what | pbg | must | the | bidder | furnish".
    Postgres drops its own stop words when it parses the expression."""
    return " | ".join(terms_of(question))


def psycopg_url(database_url: str, schema: str | None = None) -> str:
    """SQLAlchemy's `postgresql+psycopg://` as the libpq URL psycopg wants. With a schema
    (the test harness), the connection's search path is that schema and then `public`:
    Haystack registers pgvector's `vector` type by name when it connects, and the
    extension lives in `public` (migration 0023). The store qualifies every table name
    itself, so `public` on the path reaches nothing else."""
    url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    if schema:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}options=-csearch_path%3D{schema},public"
    return url


class TenantChunkStore(PgvectorDocumentStore):
    """One tenant's view of the chunk table. The table and its indexes exist before the
    first connection (migration 0023), so nothing here creates or recreates anything."""

    def __init__(self, settings: Settings, tenant_id: str, read_tenants: tuple[str, ...] = ()):
        super().__init__(
            connection_string=Secret.from_token(
                psycopg_url(settings.database_url, settings.db_schema)
            ),
            create_extension=False,
            schema_name=settings.db_schema or "public",
            table_name=TABLE,
            language="english",
            embedding_dimension=settings.embedding_dimension,
            vector_function="cosine_similarity",
            recreate_table=False,
            search_strategy="exact_nearest_neighbor",
        )
        self.tenant_id = tenant_id
        self.read_tenants = read_tenants
        # Haystack's store holds one psycopg connection; the API serves requests from a
        # thread pool, so calls on one store take turns.
        self.lock = threading.RLock()

    def _ensure_db_setup(self) -> None:
        before = self._connection
        super()._ensure_db_setup()
        if self._connection is not before and self._connection is not None:
            self._connection.execute(
                "SELECT set_config('app.tenant_id', %s, false), "
                "set_config('app.read_tenants', %s, false)",
                (self.tenant_id, ",".join(self.read_tenants)),
            )

    def _keyword_sql(
        self, query: str, top_k: int, filters: dict[str, Any] | None, *, any_word: bool
    ) -> tuple[Composed, tuple[Any, ...]]:
        """Haystack's keyword query (every word), or KEYWORD_ANY_QUERY (any word, at least
        MIN_TERMS of them) when `any_word` is set; the parameters the query needs first,
        the filters' after them."""
        sql_select = SQL(KEYWORD_ANY_QUERY if any_word else KEYWORD_QUERY).format(
            schema_name=Identifier(self.schema_name),
            table_name=Identifier(self.table_name),
            language=SQLLiteral(self.language),
            query=SQLLiteral(query),
        )
        params: tuple[Any, ...] = (query,)
        if any_word:
            terms = terms_of(query)
            params = (or_terms(query), terms, min(MIN_TERMS, len(terms)))
        sql_where: Composed | SQL = SQL("")
        if filters:
            sql_where, where_params = _convert_filters_to_where_clause_and_params(
                filters=filters, operator="AND"
            )
            params = (*params, *where_params)
        sql_sort = SQL(" ORDER BY score DESC LIMIT {top_k}").format(top_k=SQLLiteral(top_k))
        return sql_select + sql_where + sql_sort, params

    def _keyword_retrieval(
        self, query: str, *, filters: dict[str, Any] | None = None, top_k: int = 10
    ) -> list[Document]:
        """`PgvectorKeywordRetriever` calls this. Every word first (Haystack's own query);
        when nothing holds them all, any word (KEYWORD_OR_QUERY), so a question with one
        word the page does not use still finds the page; a question whose words are all
        absent finds nothing, and the caller says so without a model call."""
        if not query:
            raise ValueError("query must be a non-empty string")
        self._ensure_db_setup()
        assert self._dict_cursor is not None
        for any_word in (False, True):
            if any_word and not terms_of(query):
                continue
            sql_query, params = self._keyword_sql(query, top_k, filters, any_word=any_word)
            result = self._execute_sql(
                cursor=self._dict_cursor,
                sql_query=sql_query,
                params=params,
                error_msg="Could not retrieve documents from PgvectorDocumentStore.",
            )
            docs = _from_pg_to_haystack_documents(result.fetchall())
            if docs:
                return docs
        return []

    def chunks_of(self, document_id: str) -> list[Any]:
        with self.lock:
            return self.filter_documents(
                {"field": "meta.document_id", "operator": "==", "value": document_id}
            )


class ChunkStores:
    """The stores a process holds, one per tenant it has served."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stores: dict[tuple[str, tuple[str, ...]], TenantChunkStore] = {}
        self._lock = threading.Lock()

    def for_tenant(self, tenant_id: str, read_tenants: tuple[str, ...] = ()) -> TenantChunkStore:
        key = (tenant_id, tuple(read_tenants))
        with self._lock:
            store = self._stores.get(key)
            if store is None:
                store = self._stores[key] = TenantChunkStore(self._settings, tenant_id, key[1])
            return store
