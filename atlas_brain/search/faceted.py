"""Metadata filtering (faceted search)."""

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.models import SearchResult
from atlas_brain.search.filters import build_source_filter_sql


def search_faceted(
    query: str,
    config: AtlasConfig,
    filters: dict | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    """Browse chunks by metadata facets.

    This mode is intentionally query-agnostic: it is for filtered browsing,
    not free-text retrieval. Text queries should be handled by lexical and
    semantic search with filters applied as narrowing constraints.
    """
    conn = get_connection(config.db_path)

    where_clauses = ["1=1"]
    params = []
    filter_clauses, filter_params = build_source_filter_sql(filters, alias="s")
    where_clauses.extend(filter_clauses)
    params.extend(filter_params)

    where_sql = " AND ".join(where_clauses)
    params.append(limit)

    rows = conn.execute(
        f"""SELECT c.chunk_id, c.content, c.source_id, c.section_heading, c.speaker,
                   s.source_type, s.title
            FROM chunks c
            JOIN sources s ON c.source_id = s.source_id
            WHERE {where_sql}
            ORDER BY s.ingested_at DESC
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
