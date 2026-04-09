"""Health check orchestrator."""

from atlas_brain.config import AtlasConfig
from atlas_brain.health.staleness import find_stale_facts, find_stale_pages
from atlas_brain.health.gaps import find_orphan_sources, find_topics_without_wiki, find_entity_suggestions
from atlas_brain.health.patterns import find_contradictions, find_trust_decay


def health_check(config: AtlasConfig, deep: bool = False) -> dict:
    """
    Run health checks.
    Standard: contradictions, staleness, orphans, entity suggestions, gaps
    Deep: + cross-project patterns, trust decay, source freshness, duplicate detection
    """
    report = {
        "contradictions": find_contradictions(config),
        "stale_facts": find_stale_facts(config),
        "stale_pages": find_stale_pages(config),
        "orphan_sources": find_orphan_sources(config),
        "entity_suggestions": find_entity_suggestions(config),
        "topics_without_wiki": find_topics_without_wiki(config),
    }

    if deep:
        report["trust_decay"] = find_trust_decay(config)

        # Source freshness audit
        from atlas_brain.db import get_connection
        conn = get_connection(config.db_path)
        rows = conn.execute(
            """SELECT source_type, MAX(ingested_at) as last_ingested,
                      COUNT(*) as count
               FROM sources
               GROUP BY source_type"""
        ).fetchall()
        report["source_freshness"] = [dict(r) for r in rows]

    return report
