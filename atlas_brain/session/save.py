"""Post-session structured capture."""

import json
from datetime import datetime, timezone

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.utils.ids import generate_id


def save_session(
    config: AtlasConfig,
    agent: str | None = None,
    summary: str | None = None,
    decisions: list[str] | None = None,
    actions: list[str] | None = None,
    questions: list[str] | None = None,
    topics: list[str] | None = None,
) -> str:
    """Save a session record."""
    conn = get_connection(config.db_path)
    now = datetime.now(timezone.utc).isoformat()
    session_id = generate_id("ses")

    conn.execute(
        """INSERT INTO sessions
           (session_id, agent, started_at, ended_at, summary,
            decisions, actions, questions, topics)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, agent, now, now, summary,
         json.dumps(decisions) if decisions else None,
         json.dumps(actions) if actions else None,
         json.dumps(questions) if questions else None,
         json.dumps(topics) if topics else None),
    )
    conn.commit()
    return session_id
