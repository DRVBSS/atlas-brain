"""MCP tool definitions — 16 tools for Atlas Brain."""

import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from atlas_brain.config import AtlasConfig
from atlas_brain.db import AtlasNotInitializedError, ensure_initialized, reset_connection
from atlas_brain.validation import resolve_path_within_root, validate_topic_slug

app = Server("atlas-brain")


def _config(require_initialized: bool = True) -> AtlasConfig:
    reset_connection()
    config = AtlasConfig()
    if require_initialized:
        ensure_initialized(config.db_path)
    return config


def _text_response(payload) -> list[TextContent]:
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, indent=2)
    return [TextContent(type="text", text=text)]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="atlas_status", description="System overview: source count, fact count, health summary", inputSchema={"type": "object", "properties": {}}),
        Tool(name="atlas_ingest", description="Ingest a file into Atlas Brain", inputSchema={"type": "object", "properties": {"path": {"type": "string"}, "type": {"type": "string"}, "skip_embed": {"type": "boolean"}}, "required": ["path"]}),
        Tool(name="atlas_ingest_recall", description="Ingest a Recall (getrecall.ai) ZIP export", inputSchema={"type": "object", "properties": {"zip_path": {"type": "string"}}, "required": ["zip_path"]}),
        Tool(name="atlas_search", description="Unified search across all sources", inputSchema={"type": "object", "properties": {"query": {"type": "string"}, "modes": {"type": "array", "items": {"type": "string"}}, "top_k": {"type": "integer"}}, "required": ["query"]}),
        Tool(name="atlas_get_source", description="Get a source with its processed text", inputSchema={"type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"]}),
        Tool(name="atlas_get_topic", description="Get a wiki page by slug", inputSchema={"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"]}),
        Tool(name="atlas_compile_topic", description="Compile or update a wiki page", inputSchema={"type": "object", "properties": {"slug": {"type": "string"}, "force": {"type": "boolean"}}, "required": ["slug"]}),
        Tool(name="atlas_add_fact", description="Add a canonical fact", inputSchema={"type": "object", "properties": {"subject": {"type": "string"}, "predicate": {"type": "string"}, "object": {"type": "string"}, "source_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["subject", "predicate", "object", "source_ids"]}),
        Tool(name="atlas_query_facts", description="Query canonical facts", inputSchema={"type": "object", "properties": {"subject": {"type": "string"}, "predicate": {"type": "string"}, "current": {"type": "boolean"}, "confidence": {"type": "string"}}}),
        Tool(name="atlas_promote", description="Promote a fact candidate", inputSchema={"type": "object", "properties": {"candidate_id": {"type": "string"}}, "required": ["candidate_id"]}),
        Tool(name="atlas_get_entity", description="Get an entity with relationships", inputSchema={"type": "object", "properties": {"entity_id": {"type": "string"}}, "required": ["entity_id"]}),
        Tool(name="atlas_find_related", description="Find related entities", inputSchema={"type": "object", "properties": {"entity_id": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["entity_id"]}),
        Tool(name="atlas_contradictions", description="Get contradictions", inputSchema={"type": "object", "properties": {"resolved": {"type": "boolean"}}}),
        Tool(name="atlas_gaps", description="Analyze coverage gaps", inputSchema={"type": "object", "properties": {}}),
        Tool(name="atlas_health_check", description="Run health check", inputSchema={"type": "object", "properties": {"deep": {"type": "boolean"}}}),
        Tool(name="atlas_session_save", description="Save session intelligence", inputSchema={"type": "object", "properties": {"summary": {"type": "string"}, "decisions": {"type": "array", "items": {"type": "string"}}, "actions": {"type": "array", "items": {"type": "string"}}}}),
        Tool(name="atlas_session_brief", description="Generate pre-session context brief", inputSchema={"type": "object", "properties": {}}),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        config = _config()
    except AtlasNotInitializedError as e:
        return _text_response({"error": str(e)})

    if name == "atlas_status":
        from atlas_brain.db import get_connection
        conn = get_connection(config.db_path)
        result = {
            "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "facts": conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
            "candidates": conn.execute("SELECT COUNT(*) FROM fact_candidates WHERE promoted=0 AND rejected=0").fetchone()[0],
            "entities": conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            "wiki_pages": conn.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0],
        }
        return _text_response(result)

    elif name == "atlas_ingest":
        from atlas_brain.ingest.pipeline import ingest_file
        try:
            target = resolve_path_within_root(arguments["path"], config)
        except ValueError as e:
            return _text_response({"error": str(e)})
        if not target.is_file():
            return _text_response({"error": "Path must point to a file within the Atlas root"})
        result = ingest_file(
            target,
            config,
            explicit_type=arguments.get("type"),
            skip_embeddings=arguments.get("skip_embed", False),
        )
        return _text_response({"source_id": result.source_id, "status": result.status, "errors": result.errors})

    elif name == "atlas_ingest_recall":
        from atlas_brain.ingest.pipeline import ingest_recall_export
        results = ingest_recall_export(Path(arguments["zip_path"]), config)
        summary = {
            "total": len(results),
            "success": sum(1 for r in results if r.status == "success"),
            "partial": sum(1 for r in results if r.status == "partial"),
            "failed": sum(1 for r in results if r.status == "failed"),
            "source_ids": [r.source_id for r in results if r.source_id],
        }
        return _text_response(summary)

    elif name == "atlas_search":
        from atlas_brain.search.unified import SearchExecutionError, search
        try:
            results = search(arguments["query"], config, modes=arguments.get("modes"), top_k=arguments.get("top_k", 10))
        except ValueError as e:
            return _text_response({"error": str(e)})
        except SearchExecutionError as e:
            error = {"error": str(e), "failed_modes": e.failures}
            return _text_response(error)
        output = [{"chunk_id": r.chunk_id, "content": r.content[:500], "source_id": r.source_id, "source_type": r.source_type, "title": r.source_title, "score": r.relevance_score, "citation": r.citation} for r in results]
        return _text_response(output)

    elif name == "atlas_get_source":
        from atlas_brain.db import get_connection
        conn = get_connection(config.db_path)
        row = conn.execute("SELECT * FROM sources WHERE source_id = ?", (arguments["source_id"],)).fetchone()
        if not row:
            return _text_response("Source not found")
        result = dict(row)
        # Include processed text
        processed_path = row["processed_path"]
        if processed_path and Path(processed_path).exists():
            result["processed_text"] = Path(processed_path).read_text()[:10000]
        return _text_response(result)

    elif name == "atlas_get_topic":
        try:
            slug = validate_topic_slug(arguments["slug"])
        except ValueError as e:
            return _text_response({"error": str(e)})
        wiki_path = config.wiki_dir / f"{slug}.md"
        if wiki_path.exists():
            return _text_response(wiki_path.read_text())
        return _text_response(f"Wiki page '{slug}' not found")

    elif name == "atlas_compile_topic":
        from atlas_brain.wiki.compiler import compile_topic
        from atlas_brain.wiki.index import update_index
        try:
            path = compile_topic(arguments["slug"], config, force=arguments.get("force", False))
        except ValueError as e:
            return _text_response({"error": str(e)})
        update_index(config)
        return _text_response(path.read_text())

    elif name == "atlas_add_fact":
        from atlas_brain.knowledge.facts import add_fact
        try:
            fact = add_fact(arguments["subject"], arguments["predicate"], arguments["object"], arguments["source_ids"], config)
        except ValueError as e:
            return _text_response({"error": str(e)})
        return _text_response({"fact_id": fact.fact_id, "confidence": fact.confidence})

    elif name == "atlas_query_facts":
        from atlas_brain.knowledge.facts import query_facts
        facts = query_facts(config, subject=arguments.get("subject"), predicate=arguments.get("predicate"), current=arguments.get("current", False), confidence=arguments.get("confidence"))
        output = [{"fact_id": f.fact_id, "subject": f.subject, "predicate": f.predicate, "object": f.object, "confidence": f.confidence, "source_ids": f.source_ids} for f in facts]
        return _text_response(output)

    elif name == "atlas_promote":
        from atlas_brain.knowledge.facts import promote_candidate
        try:
            fact = promote_candidate(arguments["candidate_id"], config)
        except ValueError as e:
            return _text_response({"error": str(e)})
        return _text_response({"fact_id": fact.fact_id, "confidence": fact.confidence})

    elif name == "atlas_get_entity":
        from atlas_brain.knowledge.entities import get_entity, find_related
        entity = get_entity(arguments["entity_id"], config)
        if not entity:
            return _text_response("Entity not found")
        rels = find_related(arguments["entity_id"], config)
        result = {"entity_id": entity.entity_id, "name": entity.name, "type": entity.entity_type, "aliases": entity.aliases, "relationships": [{"rel_id": r.rel_id, "type": r.rel_type, "from": r.from_entity, "to": r.to_entity} for r in rels]}
        return _text_response(result)

    elif name == "atlas_find_related":
        from atlas_brain.knowledge.entities import find_related
        rels = find_related(arguments["entity_id"], config, depth=arguments.get("depth", 1))
        output = [{"rel_id": r.rel_id, "type": r.rel_type, "from": r.from_entity, "to": r.to_entity, "confidence": r.confidence} for r in rels]
        return _text_response(output)

    elif name == "atlas_contradictions":
        from atlas_brain.knowledge.contradictions import get_unresolved
        contras = get_unresolved(config)
        return _text_response(contras)

    elif name == "atlas_gaps":
        from atlas_brain.health.gaps import find_orphan_sources, find_topics_without_wiki, find_entity_suggestions
        result = {"orphan_sources": find_orphan_sources(config), "topics_without_wiki": find_topics_without_wiki(config), "entity_suggestions": find_entity_suggestions(config)}
        return _text_response(result)

    elif name == "atlas_health_check":
        from atlas_brain.health.checker import health_check
        report = health_check(config, deep=arguments.get("deep", False))
        return _text_response(report)

    elif name == "atlas_session_save":
        from atlas_brain.session.save import save_session
        session_id = save_session(config, summary=arguments.get("summary"), decisions=arguments.get("decisions"), actions=arguments.get("actions"))
        return _text_response({"session_id": session_id})

    elif name == "atlas_session_brief":
        from atlas_brain.session.brief import generate_brief
        brief = generate_brief(config)
        return _text_response(brief)

    return _text_response(f"Unknown tool: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
