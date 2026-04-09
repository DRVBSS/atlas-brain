"""Vector similarity search via ChromaDB."""

import logging

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.models import SearchResult
from atlas_brain.search.filters import build_chroma_where, matches_source_filters, normalize_filters

logger = logging.getLogger(__name__)


def search_semantic(
    query: str,
    config: AtlasConfig,
    filters: dict | None = None,
    limit: int = 20,
) -> list[SearchResult]:
    """Search using ChromaDB vector similarity."""
    from atlas_brain.ingest.embedder import (
        _get_chroma_collection,
        _get_embed_model,
        ensure_embedding_metadata,
    )

    if not query.strip():
        return []

    model = _get_embed_model()
    normalized_filters = normalize_filters(filters)
    if normalized_filters:
        ensure_embedding_metadata(config)
    collection = _get_chroma_collection(config)

    if collection.count() == 0:
        return []

    # Generate query embedding
    query_embedding = model.encode([query], show_progress_bar=False).tolist()

    # Query ChromaDB with exact metadata pushdown when filters are present.
    chroma_where = build_chroma_where(normalized_filters)

    chroma_results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(limit, collection.count()),
        where=chroma_where,
    )

    if not chroma_results["ids"] or not chroma_results["ids"][0]:
        return []

    # Enrich with source metadata
    conn = get_connection(config.db_path)
    results = []

    for i, chunk_id in enumerate(chroma_results["ids"][0]):
        distance = chroma_results["distances"][0][i] if chroma_results.get("distances") else 0
        score = 1.0 / (1.0 + distance)

        row = conn.execute(
            """SELECT c.chunk_id, c.content, c.source_id, c.section_heading, c.speaker,
                      s.source_type, s.title, s.author, s.created_date
               FROM chunks c
               JOIN sources s ON c.source_id = s.source_id
               WHERE c.chunk_id = ?""",
            (chunk_id,),
        ).fetchone()

        if row and matches_source_filters(row, normalized_filters):
            results.append(SearchResult(
                chunk_id=row["chunk_id"],
                content=row["content"],
                source_id=row["source_id"],
                source_type=row["source_type"],
                source_title=row["title"],
                section_heading=row["section_heading"],
                speaker=row["speaker"],
                relevance_score=score,
                citation=f"[src:{row['source_id']}]",
            ))
            if len(results) >= limit:
                break

    return results
