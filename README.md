# Atlas Brain

**A local-first cognitive operating system for humans and AI agents.**

Your memory system should be smarter than a search engine, more trustworthy than an AI summary, and more durable than any single tool you use today.

---

## The Problem

Two approaches to personal AI knowledge bases defined the space — and both fell short.

**The [Karpathy-style knowledge base](https://x.com/karpathy)** nails simplicity. Three folders, a schema file, and an AI that compiles a wiki. Anyone can start in ten minutes. But it has no retrieval beyond "read the whole folder," no provenance, no temporal awareness, and no way for an AI agent to query it programmatically. The wiki silently becomes truth, errors compound, and there's no mechanism to distinguish what you *know* from what the AI *generated*.

**[MemPalace](https://github.com/mfrederickson/mempalace)** goes deeper on retrieval and persistence. It stores conversations verbatim, uses ChromaDB for semantic search, builds a temporal knowledge graph, and exposes 19 MCP tools. But it's tightly coupled to its own metaphor, treats vector search as the primary source of truth, and assumes conversations are the primary input — not the mixed reality of files, code, meeting notes, and research that professionals actually produce.

## The Solution

**Atlas Brain** takes the best ideas from both and builds the system that should have existed from the start.

From the Karpathy approach: file-first simplicity, human-readable markdown wiki, zero infrastructure to start.

From MemPalace: semantic vector search, structured retrieval, programmatic access via MCP tools.

From neither: **a trust model that treats AI-generated knowledge as a hypothesis, not a fact.** Every claim extracted by AI starts as a candidate. It earns canonical status only through multi-source corroboration or human confirmation. Contradictions are detected and flagged, not silently resolved.

The result is a 51-module Python system with a 9-step ingestion pipeline, hybrid search, trust-scored fact management, auto-compiled wiki with citations, and three interfaces (CLI, MCP, REST) — all running locally, all under your control.

---

## What It Does

- **Ingest anything** — PDF, DOCX, PPTX, Markdown, source code, conversations, media, [Recall](https://getrecall.ai) exports
- **Search with hybrid retrieval** — FTS5 lexical + ChromaDB semantic search, merged with Reciprocal Rank Fusion
- **Extract and score facts** — AI finds structured triples (subject/predicate/object), trust model scores them from TENTATIVE through VERIFIED
- **Catch contradictions** — Automatic detection when facts from different sources conflict
- **Compile a living wiki** — Auto-generated topic pages with full source citations and change tracking
- **Access from anywhere** — CLI for humans, MCP server (16 tools) for AI agents, REST API for everything else

---

## Quick Start

```bash
# Install
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .

# Initialize a knowledge base
atlas init ~/my-brain

# Ingest files
cd ~/my-brain
atlas ingest ~/Documents/article.pdf
atlas ingest ~/Downloads/notes/          # whole directory

# Search
atlas search "knowledge management"
atlas search "query" --mode semantic     # semantic only

# Review AI-extracted facts
atlas facts candidates                   # see what AI found
atlas fact promote <candidate_id>        # approve it
atlas fact reject <candidate_id>         # discard it

# Wiki
atlas wiki compile my-topic
atlas wiki list

# Health
atlas status
atlas health --deep
atlas contradictions
atlas gaps

# Servers
atlas serve mcp                          # for Claude, Cursor, etc.
atlas serve rest --port 7437             # REST API on localhost
```

---

## Architecture

```
my-brain/
├── ATLAS.md                  # System schema + agent instructions
├── inbox/                    # Drop zone for unprocessed material
├── sources/                  # Immutable originals (never modified)
│   ├── articles/
│   ├── conversations/
│   ├── documents/
│   ├── code/
│   ├── meetings/
│   ├── media/
│   └── exports/
├── processed/                # Extracted text (.md)
├── wiki/                     # Compiled topic pages with citations
├── state/
│   ├── atlas.db              # SQLite with FTS5, WAL mode
│   └── chroma/               # ChromaDB vector store
└── logs/
```

### Trust Model

AI-extracted facts are not treated as truth. They earn it.

```
TENTATIVE ──→ DERIVED ──→ VERIFIED
    │             │            │
    └──→ STALE ←──┘←───────────┘
              ↕
           DISPUTED
```

| Level | Meaning | How it gets there |
|-------|---------|-------------------|
| **TENTATIVE** | Single-source AI extraction | Auto-promoted on ingest |
| **DERIVED** | Corroborated by 2+ sources | Auto-promoted when a second source agrees |
| **VERIFIED** | Human-confirmed | `atlas fact promote` or manual add |
| **DISPUTED** | Contradicted by another fact | Auto-detected on ingest |
| **STALE** | Not verified within freshness window | Time-based decay |

### Ingestion Pipeline

Every file passes through 9 steps:

1. **Classify** — Detect source type (article, conversation, code, etc.)
2. **Archive** — Copy to `sources/`, SHA-256 hash for dedup
3. **Extract** — Pull text via type-specific extractor
4. **Manifest** — Record in SQLite
5. **Chunk** — Split at semantic boundaries (headings, paragraphs, speaker turns)
6. **Embed** — Generate vectors via nomic-embed-text-v1.5 into ChromaDB
7. **FTS Index** — Insert into SQLite FTS5 for keyword search
8. **Fact Extract** — AI extracts structured triples via local or cloud LLM
9. **Log** — Record pipeline result and timing

Steps 6-8 run in parallel. Use `--skip-embed` for fast bulk ingestion.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| CLI | Typer + Rich |
| Database | SQLite (FTS5, WAL mode) |
| Vectors | ChromaDB + nomic-embed-text-v1.5 |
| Extractors | pdfplumber, python-docx, python-pptx, markitdown |
| LLM | Auto-detected: msty.ai, Ollama, llama.cpp, Claude, OpenAI ([setup guide](docs/CONFIGURATION.md)) |
| MCP Server | mcp library (stdio) — 16 tools |
| REST API | FastAPI + uvicorn |

## MCP Tools

Atlas Brain exposes 16 MCP tools for AI agent integration:

`atlas_status` `atlas_ingest` `atlas_ingest_recall` `atlas_search` `atlas_get_source` `atlas_get_topic` `atlas_compile_topic` `atlas_add_fact` `atlas_query_facts` `atlas_promote` `atlas_get_entity` `atlas_find_related` `atlas_contradictions` `atlas_gaps` `atlas_health_check` `atlas_session_save` `atlas_session_brief`

---

## Design Principles

1. **Files are sovereign.** Source files in `sources/` are never modified, renamed, or deleted. If the database is lost, everything rebuilds from files.

2. **Derived knowledge must earn trust.** AI-generated facts start as candidates, not truth. Promotion requires corroboration or human confirmation.

3. **Lower tiers override upper tiers.** Source files override facts. Facts override wiki. Wiki overrides outputs.

4. **Every claim is traceable.** Wiki pages cite source IDs. Facts link to their provenance. Nothing exists without a trail.

5. **Works with any AI tool.** CLI for terminals, MCP for Claude/Cursor, REST for everything else. No vendor lock-in.

---

## Configuration

See **[docs/CONFIGURATION.md](docs/CONFIGURATION.md)** for full setup instructions:

- Choosing and configuring your LLM backend (msty.ai, Ollama, llama.cpp, Claude, OpenAI, or any OpenAI-compatible server)
- Custom ports and environment variables
- Embedding model setup
- Verifying your installation

## Testing

```bash
pip install -e ".[test]"
python -m pytest tests/ -v
```

12 smoke tests covering initialization safety, search injection prevention, fact promotion, contradiction detection, API path validation, and wiki compilation.

---

## Origin

Atlas Brain was designed by analyzing the strengths and weaknesses of two existing approaches to AI knowledge management — the Karpathy-style file-and-wiki simplicity and MemPalace's structured retrieval — then building the system that neither one could be on its own. The full design rationale lives in [`docs/design/`](docs/design/).

---

## License

Private — all rights reserved.
