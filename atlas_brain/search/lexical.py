"""FTS5-based lexical search."""

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.models import SearchResult
from atlas_brain.search.filters import build_source_filter_sql

import re

_FTS5_KEYWORDS = {"AND", "OR", "NOT", "NEAR"}
_FTS5_TOKENS = re.compile(r"\b\w{2,}\b", flags=re.UNICODE)


def _sanitize_fts_query(query: str) -> str:
    """Convert raw user input into a safe FTS5 query.

    Splits into plain word tokens, strips FTS5 keywords/operators,
    and quotes each token so reserved words cannot alter the query.
    """
    tokens = [
        match.group(0)
        for match in _FTS5_TOKENS.finditer(query)
        if match.group(0).upper() not in _FTS5_KEYWORDS
    ]

    if not tokens:
        return '""'

    return " ".join(f'"{token}"' for token in tokens)


def search_lexical(
    query: str,
    config: AtlasConfig,
    filters: dict | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    """Search using SQLite FTS5."""
    conn = get_connection(config.db_path)

    fts_query = _sanitize_fts_query(query)
    where_clauses = ["chunks_fts MATCH ?"]
    params = [fts_query]
    filter_clauses, filter_params = build_source_filter_sql(filters, alias="s")
    where_clauses.extend(filter_clauses)
    params.extend(filter_params)
    where_sql = " AND ".join(where_clauses)
    params.append(limit)

    rows = conn.execute(
        """SELECT c.chunk_id, c.content, c.source_id, c.section_heading, c.speaker,
                  s.source_type, s.title,
                  rank
           FROM chunks_fts
           JOIN chunks c ON chunks_fts.rowid = c.rowid
           JOIN sources s ON c.source_id = s.source_id
           WHERE """
        + where_sql +
        """
           ORDER BY rank
           LIMIT ?""",
        params,
    ).fetchall()

    results = []
    for i, row in enumerate(rows):
        results.append(SearchResult(
            chunk_id=row["chunk_id"],
            content=row["content"],
            source_id=row["source_id"],
            source_type=row["source_type"],
            source_title=row["title"],
            section_heading=row["section_heading"],
            speaker=row["speaker"],
            relevance_score=1.0 / (i + 1),
            citation=f"[src:{row['source_id']}]",
        ))

    return results
