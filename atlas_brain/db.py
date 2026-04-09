"""SQLite connection management and schema creation."""

import sqlite3
import threading
from pathlib import Path

_local = threading.local()


class AtlasNotInitializedError(RuntimeError):
    """Raised when Atlas Brain commands run before `atlas init`."""


_REQUIRED_TABLES = {
    "sources",
    "chunks",
    "fact_candidates",
    "facts",
    "entities",
    "relationships",
    "wiki_pages",
    "trust_events",
    "contradictions",
    "sessions",
    "ingest_log",
    "chunks_fts",
}

SCHEMA_SQL = """
-- Sources: immutable record of everything ingested
CREATE TABLE IF NOT EXISTS sources (
    source_id       TEXT PRIMARY KEY,
    original_path   TEXT NOT NULL,
    processed_path  TEXT,
    source_type     TEXT NOT NULL CHECK(source_type IN (
        'article', 'conversation', 'document', 'code', 'meeting', 'media', 'export'
    )),
    content_hash    TEXT NOT NULL,
    title           TEXT,
    author          TEXT,
    created_date    TEXT,
    ingested_at     TEXT NOT NULL,
    word_count      INTEGER,
    language        TEXT DEFAULT 'en',
    metadata        TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash);

-- Chunks: semantic segments of processed text
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES sources(source_id),
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    section_heading TEXT,
    speaker         TEXT,
    token_count     INTEGER,
    embedding_id    TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);

-- Fact candidates: staging table for AI-extracted facts (NOT canonical)
CREATE TABLE IF NOT EXISTS fact_candidates (
    candidate_id    TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL REFERENCES sources(source_id),
    subject         TEXT NOT NULL,
    predicate       TEXT NOT NULL,
    object          TEXT NOT NULL,
    valid_from      TEXT,
    valid_to        TEXT,
    extraction_model TEXT,
    extracted_at    TEXT NOT NULL,
    promoted        INTEGER DEFAULT 0,
    rejected        INTEGER DEFAULT 0
);

-- Facts: canonical structured claims with provenance
CREATE TABLE IF NOT EXISTS facts (
    fact_id         TEXT PRIMARY KEY,
    subject         TEXT NOT NULL,
    predicate       TEXT NOT NULL,
    object          TEXT NOT NULL,
    confidence      TEXT DEFAULT 'TENTATIVE' CHECK(confidence IN (
        'VERIFIED', 'DERIVED', 'TENTATIVE', 'DISPUTED', 'STALE'
    )),
    valid_from      TEXT,
    valid_to        TEXT,
    source_ids      TEXT NOT NULL,
    extracted_by    TEXT,
    extracted_at    TEXT NOT NULL,
    verified_at     TEXT,
    verified_by     TEXT,
    superseded_by   TEXT REFERENCES facts(fact_id),
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(subject);
CREATE INDEX IF NOT EXISTS idx_facts_confidence ON facts(confidence);
CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_canonical_triple
    ON facts(subject, predicate, object) WHERE superseded_by IS NULL;

-- Indexes for promotion/contradiction scan performance
CREATE INDEX IF NOT EXISTS idx_fact_candidates_pending
    ON fact_candidates(promoted, rejected, subject, predicate, object);

-- Entities: people, projects, companies, technologies
CREATE TABLE IF NOT EXISTS entities (
    entity_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    entity_type     TEXT NOT NULL CHECK(entity_type IN (
        'person', 'project', 'company', 'technology', 'concept', 'event', 'location'
    )),
    aliases         TEXT,
    first_seen      TEXT,
    last_seen       TEXT,
    metadata        TEXT
);

-- Relationships: connections between entities
CREATE TABLE IF NOT EXISTS relationships (
    rel_id          TEXT PRIMARY KEY,
    from_entity     TEXT NOT NULL REFERENCES entities(entity_id),
    to_entity       TEXT NOT NULL REFERENCES entities(entity_id),
    rel_type        TEXT NOT NULL,
    valid_from      TEXT,
    valid_to        TEXT,
    source_ids      TEXT NOT NULL,
    confidence      TEXT DEFAULT 'DERIVED'
);

-- Wiki pages: metadata for wiki/ markdown files
CREATE TABLE IF NOT EXISTS wiki_pages (
    page_id         TEXT PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    confidence      TEXT DEFAULT 'DERIVED',
    source_count    INTEGER DEFAULT 0,
    fact_count      INTEGER DEFAULT 0,
    last_compiled   TEXT,
    last_verified   TEXT,
    freshness_days  INTEGER DEFAULT 90
);

-- Trust events: audit trail for confidence changes
CREATE TABLE IF NOT EXISTS trust_events (
    event_id        TEXT PRIMARY KEY,
    target_type     TEXT NOT NULL CHECK(target_type IN ('fact', 'wiki_page', 'output')),
    target_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL CHECK(event_type IN (
        'created', 'corroborated', 'disputed', 'verified_human', 'decayed', 'superseded'
    )),
    old_confidence  TEXT,
    new_confidence  TEXT,
    reason          TEXT,
    source_id       TEXT,
    timestamp       TEXT NOT NULL
);

-- Contradictions: detected conflicts between facts
CREATE TABLE IF NOT EXISTS contradictions (
    contradiction_id TEXT PRIMARY KEY,
    fact_id_a       TEXT NOT NULL REFERENCES facts(fact_id),
    fact_id_b       TEXT NOT NULL REFERENCES facts(fact_id),
    conflict_type   TEXT CHECK(conflict_type IN ('value', 'temporal', 'attribution')),
    detected_at     TEXT NOT NULL,
    resolved_at     TEXT,
    resolution      TEXT CHECK(resolution IN ('a_wins', 'b_wins', 'both_valid', 'merged')),
    resolved_by     TEXT
);

-- Sessions: conversation continuity across AI tools
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    agent           TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    summary         TEXT,
    decisions       TEXT,
    actions         TEXT,
    questions       TEXT,
    topics          TEXT
);

-- Ingest log: pipeline audit trail
CREATE TABLE IF NOT EXISTS ingest_log (
    log_id          TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    status          TEXT NOT NULL CHECK(status IN ('success', 'partial', 'failed')),
    steps_completed TEXT,
    errors          TEXT,
    duration_ms     INTEGER,
    timestamp       TEXT NOT NULL
);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content, section_heading, speaker,
    content=chunks, content_rowid=rowid
);
"""


def _has_required_schema(conn: sqlite3.Connection) -> bool:
    """Return whether the database has the Atlas schema."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    table_names = {row[0] if not isinstance(row, sqlite3.Row) else row["name"] for row in rows}
    return _REQUIRED_TABLES.issubset(table_names)


def is_initialized(db_path: Path) -> bool:
    """Return whether the database file exists and has the expected schema."""
    if not db_path.exists():
        return False

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return _has_required_schema(conn)
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def ensure_initialized(db_path: Path) -> None:
    """Raise a friendly error when Atlas Brain has not been initialized yet."""
    if not is_initialized(db_path):
        raise AtlasNotInitializedError("Atlas Brain not initialized. Run `atlas init` first.")


def get_connection(
    db_path: Path,
    *,
    allow_uninitialized: bool = False,
) -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection."""
    if not allow_uninitialized and not db_path.exists():
        raise AtlasNotInitializedError("Atlas Brain not initialized. Run `atlas init` first.")

    conn = getattr(_local, "connection", None)
    db_str = str(db_path)
    # Check if connection is for the right database and still open
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            if getattr(_local, "db_path", None) == db_str:
                if not allow_uninitialized and not _has_required_schema(conn):
                    raise AtlasNotInitializedError(
                        "Atlas Brain not initialized. Run `atlas init` first."
                    )
                return conn
            conn.close()
        except Exception:
            pass

    conn = sqlite3.connect(db_str)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    if not allow_uninitialized and not _has_required_schema(conn):
        conn.close()
        raise AtlasNotInitializedError("Atlas Brain not initialized. Run `atlas init` first.")
    _local.connection = conn
    _local.db_path = db_str
    return conn


def close_connection() -> None:
    """Close the thread-local connection."""
    conn = getattr(_local, "connection", None)
    if conn is not None:
        conn.close()
        _local.connection = None
        _local.db_path = None


def init_schema(db_path: Path) -> None:
    """Create all tables and indexes."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path, allow_uninitialized=True)
    conn.executescript(SCHEMA_SQL)
    conn.executescript(FTS_SQL)
    conn.commit()


def reset_connection() -> None:
    """Reset the thread-local connection."""
    close_connection()
