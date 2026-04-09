"""Coverage analysis."""

import json
from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection


def find_orphan_sources(config: AtlasConfig) -> list[str]:
    """Find sources not linked to any wiki page or fact."""
    conn = get_connection(config.db_path)

    all_sources = {r["source_id"] for r in conn.execute("SELECT source_id FROM sources").fetchall()}
    fact_sources = set()
    for row in conn.execute("SELECT source_ids FROM facts").fetchall():
        try:
            ids = json.loads(row["source_ids"])
            fact_sources.update(ids)
        except (json.JSONDecodeError, TypeError):
            pass

    return list(all_sources - fact_sources)


def find_topics_without_wiki(config: AtlasConfig) -> list[str]:
    """Find topics that have sources but no wiki page."""
    conn = get_connection(config.db_path)

    # Get all unique subjects from facts
    fact_subjects = {
        r["subject"] for r in
        conn.execute("SELECT DISTINCT subject FROM facts").fetchall()
    }

    # Get all wiki slugs
    wiki_slugs = {
        r["slug"] for r in
        conn.execute("SELECT slug FROM wiki_pages").fetchall()
    }

    # Normalize for comparison
    def to_slug(s):
        return s.lower().replace(" ", "-")

    return [s for s in fact_subjects if to_slug(s) not in wiki_slugs]


def find_entity_suggestions(config: AtlasConfig, min_count: int = 3) -> list[str]:
    """Find names/terms appearing 3+ times in chunks without entity records."""
    conn = get_connection(config.db_path)

    # Get existing entity names
    existing = {
        r["name"].lower() for r in
        conn.execute("SELECT name FROM entities").fetchall()
    }

    # Simple word frequency from chunks — look for capitalized words
    import re
    from collections import Counter

    SKIP_WORDS = {
        "the", "this", "that", "these", "those", "every", "each", "some",
        "you", "your", "they", "their", "its", "our", "his", "her",
        "don", "not", "but", "and", "for", "with", "from", "into",
        "when", "where", "what", "how", "why", "who", "which",
        "create", "save", "read", "write", "update", "delete",
        "note", "notes", "file", "files", "use", "using",
        "step", "minutes", "hours", "days",
    }

    word_counts = Counter()
    rows = conn.execute("SELECT content FROM chunks").fetchall()
    for row in rows:
        # Find capitalized multi-word phrases (likely proper nouns)
        names = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', row["content"])
        # Also single capitalized words that appear mid-sentence
        single = re.findall(r'(?<=[a-z]\s)([A-Z][a-z]{2,})\b', row["content"])
        for name in names + single:
            if name.lower() not in existing and name.lower() not in SKIP_WORDS:
                word_counts[name] += 1

    return [name for name, count in word_counts.most_common(20) if count >= min_count]
