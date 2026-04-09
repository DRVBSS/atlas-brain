"""Contradiction detection and storage."""

from datetime import datetime, timezone

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.utils.ids import generate_id


def detect_contradictions(config: AtlasConfig, source_id: str | None = None) -> list[dict]:
    """Detect and store new contradictions between facts.

    When source_id is provided, only checks facts linked to that source
    against all other facts (incremental). Otherwise scans all active facts.
    """
    conn = get_connection(config.db_path)
    now = datetime.now(timezone.utc).isoformat()

    if source_id:
        # Only check facts that include this source against everything else
        rows = conn.execute(
            """SELECT f1.fact_id as id_a, f2.fact_id as id_b,
                      f1.subject, f1.predicate,
                      f1.object as obj_a, f2.object as obj_b
               FROM facts f1
               JOIN facts f2
                 ON f1.subject = f2.subject
                 AND f1.predicate = f2.predicate
                 AND f1.object != f2.object
                 AND f1.fact_id < f2.fact_id
               WHERE f1.superseded_by IS NULL
                 AND f2.superseded_by IS NULL
                 AND (
                    EXISTS (SELECT 1 FROM json_each(f1.source_ids) WHERE value = ?)
                    OR EXISTS (SELECT 1 FROM json_each(f2.source_ids) WHERE value = ?)
                 )""",
            (source_id, source_id),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT f1.fact_id as id_a, f2.fact_id as id_b,
                      f1.subject, f1.predicate,
                      f1.object as obj_a, f2.object as obj_b
               FROM facts f1
               JOIN facts f2
                 ON f1.subject = f2.subject
                 AND f1.predicate = f2.predicate
                 AND f1.object != f2.object
                 AND f1.fact_id < f2.fact_id
               WHERE f1.superseded_by IS NULL
                 AND f2.superseded_by IS NULL"""
        ).fetchall()

    new_contradictions = []
    for row in rows:
        # Check if already recorded
        existing = conn.execute(
            """SELECT 1 FROM contradictions
               WHERE fact_id_a = ? AND fact_id_b = ?""",
            (row["id_a"], row["id_b"]),
        ).fetchone()

        if not existing:
            ctr_id = generate_id("ctr")
            conn.execute(
                """INSERT INTO contradictions
                   (contradiction_id, fact_id_a, fact_id_b, conflict_type, detected_at)
                   VALUES (?, ?, ?, 'value', ?)""",
                (ctr_id, row["id_a"], row["id_b"], now),
            )
            new_contradictions.append({
                "contradiction_id": ctr_id,
                "fact_id_a": row["id_a"],
                "fact_id_b": row["id_b"],
                "subject": row["subject"],
                "predicate": row["predicate"],
                "obj_a": row["obj_a"],
                "obj_b": row["obj_b"],
            })

    conn.commit()
    return new_contradictions


def resolve_contradiction(
    contradiction_id: str,
    resolution: str,
    resolved_by: str,
    config: AtlasConfig,
) -> None:
    """Resolve a contradiction."""
    conn = get_connection(config.db_path)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """UPDATE contradictions
           SET resolved_at = ?, resolution = ?, resolved_by = ?
           WHERE contradiction_id = ?""",
        (now, resolution, resolved_by, contradiction_id),
    )
    conn.commit()


def get_unresolved(config: AtlasConfig) -> list[dict]:
    """Get all unresolved contradictions."""
    conn = get_connection(config.db_path)
    rows = conn.execute(
        """SELECT c.*, f1.subject, f1.predicate,
                  f1.object as obj_a, f2.object as obj_b,
                  f1.confidence as conf_a, f2.confidence as conf_b
           FROM contradictions c
           JOIN facts f1 ON c.fact_id_a = f1.fact_id
           JOIN facts f2 ON c.fact_id_b = f2.fact_id
           WHERE c.resolved_at IS NULL"""
    ).fetchall()
    return [dict(r) for r in rows]
