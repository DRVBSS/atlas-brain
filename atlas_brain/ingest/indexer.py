"""Step 7: Full-text indexing via FTS5."""

from atlas_brain.models import Chunk
from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection


def index_fts(chunks: list[Chunk], config: AtlasConfig) -> None:
    """Insert chunk content into the chunks_fts FTS5 virtual table."""
    if not chunks:
        return

    conn = get_connection(config.db_path)

    for ch in chunks:
        # Get the rowid of the chunk in the chunks table
        row = conn.execute(
            "SELECT rowid FROM chunks WHERE chunk_id = ?", (ch.chunk_id,)
        ).fetchone()
        if row:
            conn.execute(
                """INSERT INTO chunks_fts(rowid, content, section_heading, speaker)
                   VALUES (?, ?, ?, ?)""",
                (row[0], ch.content, ch.section_heading or "", ch.speaker or ""),
            )

    conn.commit()
