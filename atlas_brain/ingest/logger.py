"""Step 9: Ingest logging."""

import json
from datetime import datetime, timezone

from atlas_brain.db import get_connection
from atlas_brain.config import AtlasConfig
from atlas_brain.utils.ids import generate_id


def log_ingest(
    source_id: str,
    status: str,
    steps_completed: list[str],
    errors: list[dict],
    duration_seconds: float,
    config: AtlasConfig,
) -> str:
    """Record the full pipeline run in ingest_log."""
    conn = get_connection(config.db_path)
    log_id = generate_id("log")
    conn.execute(
        """INSERT INTO ingest_log
           (log_id, source_id, status, steps_completed, errors, duration_ms, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            log_id,
            source_id,
            status,
            json.dumps(steps_completed),
            json.dumps(errors),
            int(duration_seconds * 1000),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return log_id
