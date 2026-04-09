"""Cross-source pattern detection."""

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection


def find_contradictions(config: AtlasConfig) -> list[dict]:
    """Find facts with same subject+predicate but different object."""
    conn = get_connection(config.db_path)

    rows = conn.execute(
        """SELECT f1.fact_id as id_a, f2.fact_id as id_b,
                  f1.subject, f1.predicate,
                  f1.object as obj_a, f2.object as obj_b,
                  f1.confidence as conf_a, f2.confidence as conf_b
           FROM facts f1
           JOIN facts f2
             ON f1.subject = f2.subject
             AND f1.predicate = f2.predicate
             AND f1.object != f2.object
             AND f1.fact_id < f2.fact_id
           WHERE f1.superseded_by IS NULL
             AND f2.superseded_by IS NULL"""
    ).fetchall()

    return [dict(r) for r in rows]


def find_duplicate_chunks(config: AtlasConfig, threshold: float = 0.95) -> list[dict]:
    """Find very similar chunks from different sources (deep health only)."""
    # This requires comparing embeddings — placeholder for now
    # In practice, use ChromaDB to find near-duplicates
    return []


def find_trust_decay(config: AtlasConfig, days: int = 30) -> list[dict]:
    """Find facts that have been TENTATIVE for too long."""
    conn = get_connection(config.db_path)
    rows = conn.execute(
        """SELECT fact_id, subject, predicate, object, extracted_at
           FROM facts
           WHERE confidence = 'TENTATIVE'
             AND julianday('now') - julianday(extracted_at) > ?""",
        (days,),
    ).fetchall()
    return [dict(r) for r in rows]
