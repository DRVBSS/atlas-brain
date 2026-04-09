"""Entity and relationship management."""

import json
from datetime import datetime, timezone

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.models import Entity, Relationship
from atlas_brain.utils.ids import generate_id


def create_entity(
    name: str,
    entity_type: str,
    config: AtlasConfig,
    aliases: list[str] | None = None,
    metadata: dict | None = None,
) -> Entity:
    """Create a new entity."""
    conn = get_connection(config.db_path)
    now = datetime.now(timezone.utc).isoformat()

    entity = Entity(
        entity_id=generate_id("ent"),
        name=name,
        entity_type=entity_type,
        aliases=aliases or [],
        first_seen=now,
        last_seen=now,
        metadata=metadata,
    )

    conn.execute(
        """INSERT INTO entities
           (entity_id, name, entity_type, aliases, first_seen, last_seen, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (entity.entity_id, entity.name, entity.entity_type,
         json.dumps(entity.aliases), entity.first_seen, entity.last_seen,
         json.dumps(entity.metadata) if entity.metadata else None),
    )
    conn.commit()
    return entity


def find_entity(name: str, config: AtlasConfig) -> Entity | None:
    """Find entity by name or alias."""
    conn = get_connection(config.db_path)

    # Check exact name match
    row = conn.execute(
        "SELECT * FROM entities WHERE name = ?", (name,)
    ).fetchone()

    if not row:
        # Check aliases
        rows = conn.execute("SELECT * FROM entities").fetchall()
        for r in rows:
            aliases = json.loads(r["aliases"]) if r["aliases"] else []
            if name in aliases:
                row = r
                break

    if not row:
        return None

    return Entity(
        entity_id=row["entity_id"],
        name=row["name"],
        entity_type=row["entity_type"],
        aliases=json.loads(row["aliases"]) if row["aliases"] else [],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else None,
    )


def get_entity(entity_id: str, config: AtlasConfig) -> Entity | None:
    """Get entity by ID."""
    conn = get_connection(config.db_path)
    row = conn.execute(
        "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
    ).fetchone()

    if not row:
        return None

    return Entity(
        entity_id=row["entity_id"],
        name=row["name"],
        entity_type=row["entity_type"],
        aliases=json.loads(row["aliases"]) if row["aliases"] else [],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        metadata=json.loads(row["metadata"]) if row["metadata"] else None,
    )


def create_relationship(
    from_entity: str,
    to_entity: str,
    rel_type: str,
    source_ids: list[str],
    config: AtlasConfig,
    confidence: str = "DERIVED",
) -> Relationship:
    """Create a relationship between entities."""
    conn = get_connection(config.db_path)

    rel = Relationship(
        rel_id=generate_id("rel"),
        from_entity=from_entity,
        to_entity=to_entity,
        rel_type=rel_type,
        source_ids=source_ids,
        confidence=confidence,
    )

    conn.execute(
        """INSERT INTO relationships
           (rel_id, from_entity, to_entity, rel_type, source_ids, confidence)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (rel.rel_id, rel.from_entity, rel.to_entity, rel.rel_type,
         json.dumps(rel.source_ids), rel.confidence),
    )
    conn.commit()
    return rel


def find_related(
    entity_id: str, config: AtlasConfig, depth: int = 1
) -> list[Relationship]:
    """Find relationships involving an entity."""
    conn = get_connection(config.db_path)

    rows = conn.execute(
        """SELECT * FROM relationships
           WHERE from_entity = ? OR to_entity = ?""",
        (entity_id, entity_id),
    ).fetchall()

    return [
        Relationship(
            rel_id=r["rel_id"],
            from_entity=r["from_entity"],
            to_entity=r["to_entity"],
            rel_type=r["rel_type"],
            source_ids=json.loads(r["source_ids"]) if r["source_ids"] else [],
            confidence=r["confidence"],
        )
        for r in rows
    ]
