"""Dataclasses for Atlas Brain entities."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProcessedDocument:
    """Output from a text extractor."""

    text: str
    title: str | None = None
    author: str | None = None
    created_date: str | None = None
    word_count: int = 0
    sections: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Source:
    source_id: str
    original_path: str
    processed_path: str | None = None
    source_type: str = ""
    content_hash: str = ""
    title: str | None = None
    author: str | None = None
    created_date: str | None = None
    ingested_at: str = ""
    word_count: int | None = None
    language: str = "en"
    metadata: dict[str, Any] | None = None


@dataclass
class Chunk:
    chunk_id: str
    source_id: str
    chunk_index: int
    content: str
    section_heading: str | None = None
    speaker: str | None = None
    token_count: int | None = None
    embedding_id: str | None = None


@dataclass
class FactCandidate:
    candidate_id: str
    source_id: str
    subject: str
    predicate: str
    object: str
    valid_from: str | None = None
    valid_to: str | None = None
    extraction_model: str | None = None
    extracted_at: str = ""
    promoted: int = 0
    rejected: int = 0


@dataclass
class Fact:
    fact_id: str
    subject: str
    predicate: str
    object: str
    confidence: str = "TENTATIVE"
    valid_from: str | None = None
    valid_to: str | None = None
    source_ids: list[str] = field(default_factory=list)
    extracted_by: str | None = None
    extracted_at: str = ""
    verified_at: str | None = None
    verified_by: str | None = None
    superseded_by: str | None = None
    notes: str | None = None


@dataclass
class Entity:
    entity_id: str
    name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    first_seen: str | None = None
    last_seen: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class Relationship:
    rel_id: str
    from_entity: str
    to_entity: str
    rel_type: str
    valid_from: str | None = None
    valid_to: str | None = None
    source_ids: list[str] = field(default_factory=list)
    confidence: str = "DERIVED"


@dataclass
class WikiPage:
    page_id: str
    slug: str
    title: str
    file_path: str
    confidence: str = "DERIVED"
    source_count: int = 0
    fact_count: int = 0
    last_compiled: str | None = None
    last_verified: str | None = None
    freshness_days: int = 90


@dataclass
class TrustEvent:
    event_id: str
    target_type: str
    target_id: str
    event_type: str
    old_confidence: str | None = None
    new_confidence: str | None = None
    reason: str | None = None
    source_id: str | None = None
    timestamp: str = ""


@dataclass
class Contradiction:
    contradiction_id: str
    fact_id_a: str
    fact_id_b: str
    conflict_type: str | None = None
    detected_at: str = ""
    resolved_at: str | None = None
    resolution: str | None = None
    resolved_by: str | None = None


@dataclass
class Session:
    session_id: str
    agent: str | None = None
    started_at: str = ""
    ended_at: str | None = None
    summary: str | None = None
    decisions: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


@dataclass
class IngestLog:
    log_id: str
    source_id: str
    status: str
    steps_completed: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    duration_ms: int | None = None
    timestamp: str = ""


@dataclass
class IngestResult:
    source_id: str
    status: str
    errors: list[dict] = field(default_factory=list)
    steps_completed: list[str] = field(default_factory=list)
    duration_ms: int | None = None


@dataclass
class SearchResult:
    chunk_id: str
    content: str
    source_id: str
    source_type: str
    source_title: str | None = None
    section_heading: str | None = None
    speaker: str | None = None
    relevance_score: float = 0.0
    citation: str = ""


@dataclass
class GapReport:
    topics_without_wiki: list[str] = field(default_factory=list)
    wiki_without_sources: list[str] = field(default_factory=list)
    orphan_sources: list[str] = field(default_factory=list)
    suggested_entities: list[str] = field(default_factory=list)


@dataclass
class HealthReport:
    contradictions: list[Contradiction] = field(default_factory=list)
    stale_facts: list[Fact] = field(default_factory=list)
    stale_pages: list[WikiPage] = field(default_factory=list)
    orphan_sources: list[str] = field(default_factory=list)
    suggested_entities: list[str] = field(default_factory=list)
    gaps: GapReport = field(default_factory=GapReport)
