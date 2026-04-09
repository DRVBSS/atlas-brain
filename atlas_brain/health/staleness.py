"""Freshness window checking."""

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection


def find_stale_facts(config: AtlasConfig, days: int = 30) -> list[dict]:
    """Find facts that have been TENTATIVE for more than N days."""
    conn = get_connection(config.db_path)
    rows = conn.execute(
        """SELECT fact_id, subject, predicate, object, confidence, extracted_at
           FROM facts
           WHERE confidence = 'TENTATIVE'
             AND julianday('now') - julianday(extracted_at) > ?""",
        (days,),
    ).fetchall()
    return [dict(r) for r in rows]


def find_stale_pages(config: AtlasConfig) -> list[dict]:
    """Find wiki pages past their freshness window."""
    conn = get_connection(config.db_path)
    rows = conn.execute(
        """SELECT page_id, slug, title, confidence, last_compiled, freshness_days
           FROM wiki_pages
           WHERE last_compiled IS NOT NULL
             AND julianday('now') - julianday(last_compiled) > freshness_days"""
    ).fetchall()
    return [dict(r) for r in rows]
