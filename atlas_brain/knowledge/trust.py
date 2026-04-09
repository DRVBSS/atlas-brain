"""Trust event ledger and confidence transitions."""

from datetime import datetime, timezone
from sqlite3 import Connection

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.utils.ids import generate_id

# Confidence state machine
VALID_TRANSITIONS = {
    "TENTATIVE": ["DERIVED", "VERIFIED", "DISPUTED", "STALE"],
    "DERIVED": ["VERIFIED", "DISPUTED", "STALE"],
    "VERIFIED": ["DISPUTED", "STALE"],
    "DISPUTED": ["VERIFIED", "STALE"],
    "STALE": ["VERIFIED", "DERIVED", "TENTATIVE"],
}


class InvalidTransitionError(ValueError):
    """Raised when a confidence transition violates the state machine."""
    pass


def apply_confidence_transition(
    conn: Connection,
    target_type: str,
    target_id: str,
    new_confidence: str,
    reason: str,
    source_id: str | None = None,
    event_type: str = "created",
) -> dict:
    """Apply a confidence transition on an existing connection.

    This enforces the same state machine as ``transition_confidence()``
    but leaves transaction control to the caller.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Get current confidence
    old_confidence = None
    if target_type == "fact":
        row = conn.execute("SELECT confidence FROM facts WHERE fact_id = ?", (target_id,)).fetchone()
        if row:
            old_confidence = row["confidence"]
    elif target_type == "wiki_page":
        row = conn.execute("SELECT confidence FROM wiki_pages WHERE page_id = ?", (target_id,)).fetchone()
        if row:
            old_confidence = row["confidence"]

    # Enforce state machine (skip for initial creation where old is None)
    if old_confidence is not None and old_confidence == new_confidence:
        return {"event_id": None, "old_confidence": old_confidence, "new_confidence": new_confidence}

    if old_confidence is not None:
        allowed = VALID_TRANSITIONS.get(old_confidence, [])
        if new_confidence not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition {target_type} {target_id} from {old_confidence} to {new_confidence}. "
                f"Allowed: {allowed}"
            )

    # Apply the transition
    if target_type == "fact" and old_confidence is not None:
        conn.execute(
            "UPDATE facts SET confidence = ? WHERE fact_id = ?",
            (new_confidence, target_id),
        )
    elif target_type == "wiki_page" and old_confidence is not None:
        conn.execute(
            "UPDATE wiki_pages SET confidence = ? WHERE page_id = ?",
            (new_confidence, target_id),
        )

    event_id = generate_id("evt")
    conn.execute(
        """INSERT INTO trust_events
           (event_id, target_type, target_id, event_type,
            old_confidence, new_confidence, reason, source_id, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, target_type, target_id, event_type,
         old_confidence, new_confidence, reason, source_id, now),
    )

    return {
        "event_id": event_id,
        "old_confidence": old_confidence,
        "new_confidence": new_confidence,
    }


def transition_confidence(
    target_type: str,
    target_id: str,
    new_confidence: str,
    reason: str,
    config: AtlasConfig,
    source_id: str | None = None,
    event_type: str = "created",
) -> dict:
    """Record a confidence transition in the trust ledger.

    Enforces the VALID_TRANSITIONS state machine. Raises InvalidTransitionError
    if the transition is not allowed.
    """
    conn = get_connection(config.db_path)
    result = apply_confidence_transition(
        conn,
        target_type,
        target_id,
        new_confidence,
        reason,
        source_id=source_id,
        event_type=event_type,
    )
    conn.commit()
    return result


def get_trust_history(target_id: str, config: AtlasConfig) -> list[dict]:
    """Get trust event history for a target."""
    conn = get_connection(config.db_path)
    rows = conn.execute(
        """SELECT * FROM trust_events
           WHERE target_id = ?
           ORDER BY timestamp DESC""",
        (target_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def decay_stale(config: AtlasConfig, days: int = 90) -> int:
    """Mark facts as STALE if not verified within freshness window."""
    conn = get_connection(config.db_path)
    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(
        """SELECT fact_id FROM facts
           WHERE confidence NOT IN ('STALE', 'DISPUTED')
             AND verified_at IS NOT NULL
             AND julianday('now') - julianday(verified_at) > ?""",
        (days,),
    ).fetchall()

    count = 0
    for row in rows:
        transition_confidence(
            "fact", row["fact_id"], "STALE",
            f"Not verified within {days} days",
            config, event_type="decayed",
        )
        count += 1

    return count
