"""Pre-session context generation."""

import json
from datetime import datetime, timezone

from atlas_brain.config import AtlasConfig, parse_atlas_md
from atlas_brain.db import get_connection


def generate_brief(config: AtlasConfig) -> str:
    """Generate a context brief for AI pre-loading."""
    conn = get_connection(config.db_path)
    identity = parse_atlas_md(config.atlas_md_path)

    parts = [
        "# Atlas Brain — Session Brief",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    # Identity
    if identity.get("owner"):
        parts.append(f"**Owner:** {identity['owner']}")
    if identity.get("purpose"):
        parts.append(f"**Purpose:** {identity['purpose']}")
    if identity.get("projects"):
        parts.append(f"**Active Projects:** {', '.join(identity['projects'])}")
    parts.append("")

    # Stats
    source_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    fact_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    candidate_count = conn.execute(
        "SELECT COUNT(*) FROM fact_candidates WHERE promoted=0 AND rejected=0"
    ).fetchone()[0]
    wiki_count = conn.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0]
    parts.append(f"**Sources:** {source_count} | **Facts:** {fact_count} | "
                 f"**Candidates:** {candidate_count} | **Wiki Pages:** {wiki_count}")
    parts.append("")

    # Recent sources
    recent = conn.execute(
        "SELECT source_id, title, source_type, ingested_at FROM sources ORDER BY ingested_at DESC LIMIT 5"
    ).fetchall()
    if recent:
        parts.append("## Recent Sources")
        for r in recent:
            parts.append(f"- [{r['source_id']}] {r['title'] or 'Untitled'} ({r['source_type']})")
        parts.append("")

    # Recent facts
    recent_facts = conn.execute(
        "SELECT subject, predicate, object, confidence FROM facts ORDER BY extracted_at DESC LIMIT 10"
    ).fetchall()
    if recent_facts:
        parts.append("## Recent Facts")
        for f in recent_facts:
            parts.append(f"- {f['subject']} {f['predicate']} {f['object']} [{f['confidence']}]")
        parts.append("")

    # Unresolved items
    if candidate_count > 0:
        parts.append(f"**Action needed:** {candidate_count} fact candidates awaiting review")

    contras = conn.execute(
        "SELECT COUNT(*) FROM contradictions WHERE resolved_at IS NULL"
    ).fetchone()[0]
    if contras > 0:
        parts.append(f"**Action needed:** {contras} unresolved contradictions")

    # Last session
    last_session = conn.execute(
        "SELECT summary, decisions, actions FROM sessions ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if last_session and last_session["summary"]:
        parts.append(f"\n## Last Session\n{last_session['summary']}")
        if last_session["decisions"]:
            decisions = json.loads(last_session["decisions"])
            if decisions:
                parts.append("**Decisions:** " + "; ".join(decisions))
        if last_session["actions"]:
            actions = json.loads(last_session["actions"])
            if actions:
                parts.append("**Open actions:** " + "; ".join(actions))

    return "\n".join(parts)
