# Atlas Brain — Project Instructions

## Project Description
Local-first cognitive operating system for knowledge management. Combines file-based knowledge with structured fact storage, multi-mode retrieval (lexical FTS5 + semantic ChromaDB), trust-scored AI-generated knowledge, and multi-interface access (CLI, MCP, REST).

## Tech Stack
- **Language:** Python 3.12
- **CLI:** Typer + Rich
- **Database:** SQLite (via sqlite3) with FTS5, WAL mode
- **Vectors:** ChromaDB with nomic-embed-text-v1.5
- **Extractors:** pdfplumber, python-docx, python-pptx, markitdown
- **LLM integration:** httpx calls to Ollama/Claude/OpenAI APIs
- **Servers:** MCP (mcp library), FastAPI + uvicorn
- **Package:** pyproject.toml, installed with `pip install -e .`

## Key Directories
- `atlas_brain/` — Main Python package (51 modules)
- `atlas_brain/ingest/` — 9-step ingestion pipeline
- `atlas_brain/search/` — Lexical, semantic, faceted, unified search
- `atlas_brain/knowledge/` — Facts, entities, trust, contradictions
- `atlas_brain/wiki/` — Wiki compiler and index
- `atlas_brain/health/` — Health checks and gap analysis
- `atlas_brain/server/` — MCP (16 tools) + REST API (FastAPI)
- `atlas_brain/session/` — Session brief and save

## Build / Test / Run
```bash
# Setup
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
pip install -e ".[test]"   # includes pytest, pytest-cov

# Initialize a new Atlas Brain instance
atlas init /path/to/knowledge-base

# Key commands
atlas ingest <file-or-dir> [--skip-embed]
atlas search "query" [--mode lexical|semantic|faceted]
atlas facts list | candidates
atlas fact promote <id> | reject <id> | add --subject --predicate --object --source
atlas wiki compile <slug> | --all
atlas health [--deep]
atlas status
atlas serve mcp | rest [--port N]
atlas session brief | save

# Run tests
python -m pytest tests/ -v
```

## Architecture Notes
- **Thread-safe DB:** Uses threading.local() for SQLite connections (required by parallel pipeline steps)
- **Pipeline parallelism:** Steps 7 (FTS), 8 (facts) run in parallel; embed is optional via `skip_embeddings=True`
- **Trust model:** TENTATIVE → DERIVED → VERIFIED, with DISPUTED and STALE paths
- **Files are sovereign:** source files in sources/ are never modified after ingest
- **Spec is authoritative:** docs/internal/ATLAS-BRAIN-BUILD-SPEC.md is the source of truth for all design decisions
- **Init guard:** All commands except `init` call `ensure_initialized()` — raises `AtlasNotInitializedError` if DB is missing or schema is absent
- **Input validation:** `atlas_brain/validation.py` owns path-safety and slug-safety helpers used by REST + MCP + wiki

## Conventions
- IDs use prefixed short UUIDs: src_, chk_, fct_, cand_, ent_, rel_, wiki_, evt_, ctr_, ses_, log_
- All timestamps are UTC ISO format
- JSON stored in TEXT columns for metadata, source_ids, arrays
- Extractors return `ProcessedDocument` dataclass
- Search results return `SearchResult` dataclass with citation strings

## Key Safety Rules (from QA pass, 2026-04-09)
- **Never use `LIKE '%source_id%'`** for source_id matching in contradiction detection — use `json_each()` to avoid prefix collisions
- **FTS5 keywords** (AND, OR, NOT, NEAR) must be stripped from user queries — `_sanitize_fts_query()` in `search/lexical.py` handles this
- **REST /ingest** validates that target path is within Atlas root via `resolve_path_within_root()`
- **REST /topic/{slug}** and wiki compiler validate slug with `validate_topic_slug()` — rejects path separators
- **`atlas rebuild`** is hidden (`hidden=True`) — not yet implemented
- **`atlas ingest --skip-embed`** skips embedding for fast bulk ingestion

## Docs Archive
Design history lives in `docs/design/` — not operational, kept for reference:
- `atlas-brain-blueprint.md` — original blueprint
- `hybrid-memory-blueprint.md` — predecessor research
- `sovereign-memory-system.md` — original vision
