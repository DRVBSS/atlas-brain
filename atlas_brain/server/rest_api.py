"""FastAPI REST API on localhost:7437."""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from atlas_brain.config import AtlasConfig
from atlas_brain.db import AtlasNotInitializedError, ensure_initialized, reset_connection
from atlas_brain.validation import resolve_path_within_root, validate_topic_slug

api = FastAPI(title="Atlas Brain", version="0.1.0")


def _config(require_initialized: bool = True) -> AtlasConfig:
    reset_connection()
    config = AtlasConfig()
    if require_initialized:
        ensure_initialized(config.db_path)
    return config


# -- Request models --

class IngestRequest(BaseModel):
    path: str
    type: str | None = None
    skip_embed: bool = False

class SearchRequest(BaseModel):
    query: str
    modes: list[str] | None = None
    filters: dict | None = None
    top_k: int = 10

class CompileRequest(BaseModel):
    slug: str
    force: bool = False

class FactRequest(BaseModel):
    subject: str
    predicate: str
    object: str
    source_ids: list[str]

class FactQueryRequest(BaseModel):
    subject: str | None = None
    predicate: str | None = None
    current: bool = False
    confidence: str | None = None

class PromoteRequest(BaseModel):
    id: str

class RelatedRequest(BaseModel):
    entity_id: str
    depth: int = 1

class SessionSaveRequest(BaseModel):
    summary: str | None = None
    decisions: list[str] | None = None
    actions: list[str] | None = None


@api.exception_handler(AtlasNotInitializedError)
async def handle_not_initialized(_, exc: AtlasNotInitializedError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# -- Endpoints --

@api.get("/status")
def status():
    config = _config()
    from atlas_brain.db import get_connection
    conn = get_connection(config.db_path)
    return {
        "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
        "facts": conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
        "candidates": conn.execute("SELECT COUNT(*) FROM fact_candidates WHERE promoted=0 AND rejected=0").fetchone()[0],
        "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
        "wiki_pages": conn.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0],
    }


@api.post("/ingest")
def ingest(req: IngestRequest):
    config = _config()
    from atlas_brain.ingest.pipeline import ingest_file
    try:
        target = resolve_path_within_root(req.path, config)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not target.is_file():
        raise HTTPException(400, "Path must point to a file within the Atlas root")
    result = ingest_file(
        target,
        config,
        explicit_type=req.type,
        skip_embeddings=req.skip_embed,
    )
    return {"source_id": result.source_id, "status": result.status, "errors": result.errors}


@api.post("/search")
def search_endpoint(req: SearchRequest):
    config = _config()
    from atlas_brain.search.unified import SearchExecutionError, search
    try:
        results = search(req.query, config, modes=req.modes, filters=req.filters, top_k=req.top_k)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except SearchExecutionError as e:
        raise HTTPException(503, {"message": str(e), "failed_modes": e.failures})
    return [
        {"chunk_id": r.chunk_id, "content": r.content[:500], "source_id": r.source_id,
         "source_type": r.source_type, "title": r.source_title, "score": r.relevance_score,
         "citation": r.citation}
        for r in results
    ]


@api.get("/source/{source_id}")
def get_source(source_id: str):
    config = _config()
    from atlas_brain.db import get_connection
    conn = get_connection(config.db_path)
    row = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Source not found")
    result = dict(row)
    if row["processed_path"] and Path(row["processed_path"]).exists():
        result["processed_text"] = Path(row["processed_path"]).read_text()[:10000]
    return result


@api.get("/topic/{slug}")
def get_topic(slug: str):
    config = _config()
    try:
        slug = validate_topic_slug(slug)
    except ValueError as e:
        raise HTTPException(400, str(e))
    wiki_path = config.wiki_dir / f"{slug}.md"
    if not wiki_path.exists():
        raise HTTPException(404, "Wiki page not found")
    return {"slug": slug, "content": wiki_path.read_text()}


@api.post("/topic/compile")
def compile_topic(req: CompileRequest):
    config = _config()
    from atlas_brain.wiki.compiler import compile_topic
    from atlas_brain.wiki.index import update_index
    try:
        path = compile_topic(req.slug, config, force=req.force)
    except ValueError as e:
        raise HTTPException(400, str(e))
    update_index(config)
    return {"slug": req.slug, "path": str(path)}


@api.post("/fact")
def add_fact(req: FactRequest):
    config = _config()
    from atlas_brain.knowledge.facts import add_fact
    try:
        fact = add_fact(req.subject, req.predicate, req.object, req.source_ids, config)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"fact_id": fact.fact_id, "confidence": fact.confidence}


@api.post("/facts/query")
def query_facts(req: FactQueryRequest):
    config = _config()
    from atlas_brain.knowledge.facts import query_facts
    facts = query_facts(config, subject=req.subject, predicate=req.predicate,
                        current=req.current, confidence=req.confidence)
    return [
        {"fact_id": f.fact_id, "subject": f.subject, "predicate": f.predicate,
         "object": f.object, "confidence": f.confidence, "source_ids": f.source_ids}
        for f in facts
    ]


@api.post("/promote")
def promote(req: PromoteRequest):
    config = _config()
    from atlas_brain.knowledge.facts import promote_candidate
    try:
        fact = promote_candidate(req.id, config)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"fact_id": fact.fact_id, "confidence": fact.confidence}


@api.get("/entity/{entity_id}")
def get_entity(entity_id: str):
    config = _config()
    from atlas_brain.knowledge.entities import get_entity, find_related
    entity = get_entity(entity_id, config)
    if not entity:
        raise HTTPException(404, "Entity not found")
    rels = find_related(entity_id, config)
    return {
        "entity_id": entity.entity_id, "name": entity.name,
        "type": entity.entity_type, "aliases": entity.aliases,
        "relationships": [{"rel_id": r.rel_id, "type": r.rel_type,
                          "from": r.from_entity, "to": r.to_entity} for r in rels],
    }


@api.post("/entity/related")
def find_related_endpoint(req: RelatedRequest):
    config = _config()
    from atlas_brain.knowledge.entities import find_related
    rels = find_related(req.entity_id, config, depth=req.depth)
    return [{"rel_id": r.rel_id, "type": r.rel_type, "from": r.from_entity,
             "to": r.to_entity, "confidence": r.confidence} for r in rels]


@api.get("/contradictions")
def get_contradictions():
    config = _config()
    from atlas_brain.knowledge.contradictions import get_unresolved
    return get_unresolved(config)


@api.get("/gaps")
def get_gaps():
    config = _config()
    from atlas_brain.health.gaps import find_orphan_sources, find_topics_without_wiki
    return {
        "orphan_sources": find_orphan_sources(config),
        "topics_without_wiki": find_topics_without_wiki(config),
    }


@api.get("/health")
def get_health(deep: bool = False):
    config = _config()
    from atlas_brain.health.checker import health_check
    return health_check(config, deep=deep)


@api.post("/session/save")
def save_session(req: SessionSaveRequest):
    config = _config()
    from atlas_brain.session.save import save_session
    session_id = save_session(config, summary=req.summary,
                              decisions=req.decisions, actions=req.actions)
    return {"session_id": session_id}


@api.get("/session/brief")
def session_brief():
    config = _config()
    from atlas_brain.session.brief import generate_brief
    return {"brief": generate_brief(config)}


def start(port: int = 7437):
    import uvicorn
    uvicorn.run(api, host="127.0.0.1", port=port)
