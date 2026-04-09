"""Typer CLI app — all `atlas` commands."""

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from pathlib import Path

from atlas_brain.config import AtlasConfig
from atlas_brain.db import (
    AtlasNotInitializedError,
    ensure_initialized,
    init_schema,
    reset_connection,
)
from atlas_brain.search.unified import VALID_SEARCH_MODES

app = typer.Typer(
    name="atlas",
    help="Atlas Brain — local-first cognitive operating system",
    no_args_is_help=True,
)
console = Console()

# Sub-command groups
facts_app = typer.Typer(help="Manage canonical facts")
app.add_typer(facts_app, name="facts")
fact_app = typer.Typer(help="Single fact operations")
app.add_typer(fact_app, name="fact")
wiki_app = typer.Typer(help="Wiki compilation and management")
app.add_typer(wiki_app, name="wiki")
session_app = typer.Typer(help="Session management")
app.add_typer(session_app, name="session")
serve_app = typer.Typer(help="Start servers")
app.add_typer(serve_app, name="serve")


ATLAS_MD_TEMPLATE = """# Atlas Brain — System Schema

## Identity
Owner: {owner}
Purpose: {purpose}
Active projects: {projects}
Key people: {people}

## Source Rules
- sources/ is immutable. Never modify, rename, or delete source files.
- Every source file gets a manifest entry on ingest.
- processed/ contains extracted text only. Original format lives in sources/.

## Wiki Rules
- One .md file per topic in wiki/.
- Every wiki page must cite source IDs for its claims.
- Unsourced claims are marked [UNSOURCED] and flagged for review.
- INDEX.md is auto-maintained. Never edit by hand.
- Pages include: summary, key facts, open questions, related topics,
  source references, confidence level, last verified date.

## Trust Levels
- VERIFIED: Human-confirmed or multi-source corroborated
- DERIVED: AI-generated with source citations
- TENTATIVE: Single-source or AI-inferred, awaiting confirmation
- DISPUTED: Contradicted by another source
- STALE: Not verified within its freshness window

## Agent Behavior
- When answering questions, cite source IDs.
- When unsure, say so. Never fabricate citations.
- When updating the wiki, log the change with a reason and source.
- When you encounter contradictions, flag them — don't silently resolve.
- Prefer raw source retrieval over wiki summaries for factual claims.

## Active Projects
{project_list}

## Glossary

"""


def _get_config(*, require_initialized: bool = False) -> AtlasConfig:
    """Get config from current directory."""
    config = AtlasConfig()
    if require_initialized:
        try:
            ensure_initialized(config.db_path)
        except AtlasNotInitializedError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    return config


@app.command()
def init(
    path: Path = typer.Argument(
        default=Path("."), help="Directory to initialize Atlas Brain in"
    ),
) -> None:
    """Create directory structure, database, and ATLAS.md template."""
    root = path.resolve()
    config = AtlasConfig(root=root)

    console.print(Panel("[bold]Atlas Brain — Initialization[/bold]", style="blue"))

    owner = typer.prompt("Owner name")
    purpose = typer.prompt("Purpose of this knowledge base")
    projects_raw = typer.prompt("Active projects (comma-separated)", default="")
    people_raw = typer.prompt("Key people (comma-separated)", default="")

    projects = [p.strip() for p in projects_raw.split(",") if p.strip()]
    people = [p.strip() for p in people_raw.split(",") if p.strip()]

    for d in config.all_dirs():
        d.mkdir(parents=True, exist_ok=True)
        console.print(f"  [green]✓[/green] {d.relative_to(root)}/")

    reset_connection()
    init_schema(config.db_path)
    console.print(f"  [green]✓[/green] {config.db_path.relative_to(root)}")

    if not config.atlas_md_path.exists():
        project_list = "\n".join(f"- {p}" for p in projects) if projects else "- (none yet)"
        content = ATLAS_MD_TEMPLATE.format(
            owner=owner,
            purpose=purpose,
            projects=", ".join(projects) if projects else "(none yet)",
            people=", ".join(people) if people else "(none yet)",
            project_list=project_list,
        )
        config.atlas_md_path.write_text(content)
        console.print(f"  [green]✓[/green] ATLAS.md")
    else:
        console.print(f"  [yellow]⊘[/yellow] ATLAS.md already exists, skipping")

    console.print(Panel("[bold green]Atlas Brain initialized![/bold green]", style="green"))


@app.command()
def ingest(
    path: Path = typer.Argument(help="File or directory to ingest"),
    source_type: str = typer.Option(None, "--type", "-t", help="Explicit source type override"),
    url: str = typer.Option(None, "--url", "-u", help="URL to fetch and ingest"),
    recall: bool = typer.Option(False, "--recall", help="Treat path as a Recall (getrecall.ai) ZIP export"),
    skip_embed: bool = typer.Option(
        False,
        "--skip-embed",
        help="Skip embedding generation for faster ingestion",
    ),
) -> None:
    """Ingest a file, directory, or URL into Atlas Brain."""
    from atlas_brain.ingest.pipeline import ingest_file, ingest_directory, ingest_recall_export
    from atlas_brain.ingest.archiver import DuplicateSourceError

    config = _get_config(require_initialized=True)
    reset_connection()

    if url:
        console.print(f"[yellow]URL ingestion not yet implemented[/yellow]")
        raise typer.Exit(1)

    target = path.resolve()

    # Recall ZIP export handling
    if recall or (target.suffix.lower() == ".zip" and "recall" in target.stem.lower()):
        console.print(f"[bold]Ingesting Recall export:[/bold] {target.name}")
        results = ingest_recall_export(target, config, skip_embeddings=skip_embed)
        success = sum(1 for r in results if r.status == "success")
        partial = sum(1 for r in results if r.status == "partial")
        failed = sum(1 for r in results if r.status == "failed")
        console.print(
            f"\n[green]{success} succeeded[/green], "
            f"[yellow]{partial} partial[/yellow], "
            f"[red]{failed} failed[/red] "
            f"out of {len(results)} Recall cards"
        )
        return

    if target.is_dir():
        console.print(f"[bold]Ingesting directory:[/bold] {target}")
        results = ingest_directory(target, config, skip_embeddings=skip_embed)
        success = sum(1 for r in results if r.status == "success")
        partial = sum(1 for r in results if r.status == "partial")
        failed = sum(1 for r in results if r.status == "failed")
        console.print(
            f"\n[green]{success} succeeded[/green], "
            f"[yellow]{partial} partial[/yellow], "
            f"[red]{failed} failed[/red] "
            f"out of {len(results)} files"
        )
    elif target.is_file():
        console.print(f"[bold]Ingesting:[/bold] {target.name}")
        try:
            result = ingest_file(
                target,
                config,
                explicit_type=source_type,
                skip_embeddings=skip_embed,
            )
            if result.status == "success":
                console.print(f"  [green]✓[/green] {result.source_id} — {result.duration_ms}ms")
                console.print(f"    Steps: {', '.join(result.steps_completed)}")
            elif result.status == "partial":
                console.print(f"  [yellow]⊘[/yellow] {result.source_id} — partial")
                for err in result.errors:
                    console.print(f"    [red]✗[/red] {err['step']}: {err['error']}")
            else:
                console.print(f"  [red]✗[/red] Failed")
                for err in result.errors:
                    console.print(f"    {err['step']}: {err['error']}")
        except DuplicateSourceError as e:
            console.print(f"  [yellow]⊘[/yellow] Duplicate: {e}")
    else:
        console.print(f"[red]Not found:[/red] {target}")
        raise typer.Exit(1)


@app.command()
def search(
    query: str = typer.Argument(help="Search query"),
    mode: str = typer.Option(
        None,
        "--mode",
        "-m",
        help=f"Search mode: {', '.join(VALID_SEARCH_MODES)}",
    ),
    source_type: str = typer.Option(None, "--source-type", "-s", help="Filter by source type"),
    top_k: int = typer.Option(10, "--top", "-k", help="Number of results"),
) -> None:
    """Search across all ingested sources."""
    from atlas_brain.search.unified import SearchExecutionError, search as unified_search

    config = _get_config(require_initialized=True)
    reset_connection()

    modes = [mode] if mode else None
    filters = {"source_type": source_type} if source_type else None

    try:
        results = unified_search(query, config, modes=modes, filters=filters, top_k=top_k)
    except ValueError as e:
        console.print(f"[red]Search failed:[/red] {e}")
        raise typer.Exit(1)
    except SearchExecutionError as e:
        console.print(f"[red]Search failed:[/red] {e}")
        for failed_mode, error in e.failures.items():
            console.print(f"  [red]✗[/red] {failed_mode}: {error}")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    for i, r in enumerate(results, 1):
        score_str = f"{r.relevance_score:.4f}"
        heading = f" > {r.section_heading}" if r.section_heading else ""
        console.print(
            f"\n[bold]{i}.[/bold] {r.citation} "
            f"[dim]{r.source_type}[/dim] — {r.source_title or 'untitled'}{heading} "
            f"[dim](score: {score_str})[/dim]"
        )
        # Show truncated content
        preview = r.content[:300].replace("\n", " ")
        if len(r.content) > 300:
            preview += "..."
        console.print(f"   {preview}")


@app.command()
def status() -> None:
    """System overview: source count, fact count, health."""
    config = _get_config(require_initialized=True)
    reset_connection()

    from atlas_brain.db import get_connection
    conn = get_connection(config.db_path)

    source_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    fact_count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    candidate_count = conn.execute(
        "SELECT COUNT(*) FROM fact_candidates WHERE promoted=0 AND rejected=0"
    ).fetchone()[0]
    entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    wiki_count = conn.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0]

    table = Table(title="Atlas Brain Status")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("Sources", str(source_count))
    table.add_row("Chunks", str(chunk_count))
    table.add_row("Canonical Facts", str(fact_count))
    table.add_row("Fact Candidates", str(candidate_count))
    table.add_row("Entities", str(entity_count))
    table.add_row("Wiki Pages", str(wiki_count))
    console.print(table)


@app.command()
def health(
    deep: bool = typer.Option(False, "--deep", help="Run deep health check"),
) -> None:
    """Run health checks on the knowledge base."""
    from atlas_brain.health.checker import health_check

    config = _get_config(require_initialized=True)
    reset_connection()
    report = health_check(config, deep=deep)

    console.print(Panel("[bold]Atlas Brain Health Report[/bold]", style="blue"))

    # Contradictions
    contras = report.get("contradictions", [])
    console.print(f"\n[bold]Contradictions:[/bold] {len(contras)}")
    for c in contras[:5]:
        console.print(f"  {c['subject']}.{c['predicate']}: {c['obj_a']} vs {c['obj_b']}")

    # Stale facts
    stale = report.get("stale_facts", [])
    console.print(f"\n[bold]Stale Facts (TENTATIVE > 30d):[/bold] {len(stale)}")

    # Stale pages
    stale_pages = report.get("stale_pages", [])
    console.print(f"[bold]Stale Wiki Pages:[/bold] {len(stale_pages)}")

    # Orphans
    orphans = report.get("orphan_sources", [])
    console.print(f"\n[bold]Orphan Sources (no facts):[/bold] {len(orphans)}")
    for o in orphans[:5]:
        console.print(f"  {o}")

    # Entity suggestions
    suggestions = report.get("entity_suggestions", [])
    console.print(f"\n[bold]Suggested Entities:[/bold] {len(suggestions)}")
    for s in suggestions[:10]:
        console.print(f"  {s}")

    # Topics without wiki
    topics = report.get("topics_without_wiki", [])
    console.print(f"\n[bold]Topics Without Wiki Page:[/bold] {len(topics)}")
    for t in topics[:10]:
        console.print(f"  {t}")

    if deep:
        freshness = report.get("source_freshness", [])
        console.print(f"\n[bold]Source Freshness by Type:[/bold]")
        for f in freshness:
            console.print(f"  {f['source_type']}: {f['count']} sources, last: {f['last_ingested'][:10]}")


@app.command()
def contradictions() -> None:
    """List unresolved contradictions."""
    from atlas_brain.health.patterns import find_contradictions

    config = _get_config(require_initialized=True)
    reset_connection()
    contras = find_contradictions(config)

    if not contras:
        console.print("[dim]No contradictions found.[/dim]")
        return

    for c in contras:
        console.print(f"  [bold]{c['subject']}[/bold].{c['predicate']}:")
        console.print(f"    A ({c['id_a']}): {c['obj_a']} [{c['conf_a']}]")
        console.print(f"    B ({c['id_b']}): {c['obj_b']} [{c['conf_b']}]")


@app.command()
def gaps() -> None:
    """Coverage analysis."""
    from atlas_brain.health.gaps import find_orphan_sources, find_topics_without_wiki

    config = _get_config(require_initialized=True)
    reset_connection()

    orphans = find_orphan_sources(config)
    topics = find_topics_without_wiki(config)

    console.print(f"[bold]Orphan sources (not referenced by facts):[/bold] {len(orphans)}")
    for o in orphans[:10]:
        console.print(f"  {o}")

    console.print(f"\n[bold]Topics without wiki pages:[/bold] {len(topics)}")
    for t in topics[:10]:
        console.print(f"  {t}")


@app.command(hidden=True)
def rebuild(
    from_sources: bool = typer.Option(False, "--from-sources", help="Full rebuild from source files"),
    embeddings_only: bool = typer.Option(False, "--embeddings-only", help="Rebuild vector index only"),
) -> None:
    """Rebuild the database from sources."""
    console.print("[yellow]Rebuild is temporarily hidden until a full implementation lands.[/yellow]")
    raise typer.Exit(1)


# -- Facts subcommands --

@facts_app.command("list")
def facts_list() -> None:
    """List all canonical facts."""
    from atlas_brain.knowledge.facts import query_facts

    config = _get_config(require_initialized=True)
    reset_connection()
    facts = query_facts(config)

    if not facts:
        console.print("[dim]No canonical facts yet.[/dim]")
        return

    table = Table(title="Canonical Facts")
    table.add_column("ID", style="dim")
    table.add_column("Subject")
    table.add_column("Predicate")
    table.add_column("Object")
    table.add_column("Confidence")
    table.add_column("Sources", style="dim")
    for f in facts:
        src_str = ", ".join(f.source_ids) if f.source_ids else ""
        table.add_row(f.fact_id, f.subject, f.predicate, f.object, f.confidence, src_str)
    console.print(table)


@facts_app.command("query")
def facts_query(
    subject: str = typer.Option(None, "--subject", "-s"),
    current: bool = typer.Option(False, "--current"),
) -> None:
    """Query facts by subject."""
    from atlas_brain.knowledge.facts import query_facts

    config = _get_config(require_initialized=True)
    reset_connection()
    facts = query_facts(config, subject=subject, current=current)

    if not facts:
        console.print("[dim]No matching facts.[/dim]")
        return

    for f in facts:
        console.print(f"  [bold]{f.subject}[/bold] — {f.predicate} → {f.object} [{f.confidence}]")


@facts_app.command("candidates")
def facts_candidates() -> None:
    """List unreviewed fact candidates."""
    from atlas_brain.knowledge.facts import list_candidates

    config = _get_config(require_initialized=True)
    reset_connection()
    candidates = list_candidates(config)

    if not candidates:
        console.print("[dim]No unreviewed candidates.[/dim]")
        return

    table = Table(title="Fact Candidates (unreviewed)")
    table.add_column("ID", style="dim")
    table.add_column("Subject")
    table.add_column("Predicate")
    table.add_column("Object")
    table.add_column("Source", style="dim")
    table.add_column("Model", style="dim")
    for c in candidates:
        table.add_row(c.candidate_id, c.subject, c.predicate, c.object,
                      c.source_id, c.extraction_model or "")
    console.print(table)


# -- Fact (singular) subcommands --

@fact_app.command("promote")
def fact_promote(candidate_id: str = typer.Argument(help="Candidate ID to promote")) -> None:
    """Promote a fact candidate to canonical fact."""
    from atlas_brain.knowledge.facts import promote_candidate

    config = _get_config(require_initialized=True)
    reset_connection()
    try:
        fact = promote_candidate(candidate_id, config)
        console.print(f"[green]✓[/green] Promoted to {fact.fact_id} ({fact.confidence})")
        console.print(f"  {fact.subject} — {fact.predicate} → {fact.object}")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")


@fact_app.command("reject")
def fact_reject(candidate_id: str = typer.Argument(help="Candidate ID to reject")) -> None:
    """Reject a fact candidate."""
    from atlas_brain.knowledge.facts import reject_candidate

    config = _get_config(require_initialized=True)
    reset_connection()
    try:
        reject_candidate(candidate_id, config)
        console.print(f"[green]✓[/green] Rejected {candidate_id}")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")


@fact_app.command("add")
def fact_add(
    subject: str = typer.Option(..., "--subject", "-s"),
    predicate: str = typer.Option(..., "--predicate", "-p"),
    obj: str = typer.Option(..., "--object", "-o"),
    source: str = typer.Option(..., "--source"),
) -> None:
    """Manually add a canonical fact."""
    from atlas_brain.knowledge.facts import add_fact

    config = _get_config(require_initialized=True)
    reset_connection()
    try:
        fact = add_fact(subject, predicate, obj, [source], config)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Created {fact.fact_id} ({fact.confidence})")
    console.print(f"  {fact.subject} — {fact.predicate} → {fact.object}")


# -- Wiki subcommands --

@wiki_app.command("compile")
def wiki_compile(
    topic: str = typer.Argument(None, help="Topic slug to compile"),
    all_topics: bool = typer.Option(False, "--all"),
    stale: bool = typer.Option(False, "--stale"),
) -> None:
    """Compile or update wiki pages."""
    from atlas_brain.wiki.compiler import compile_topic, compile_all
    from atlas_brain.wiki.index import update_index

    config = _get_config(require_initialized=True)
    reset_connection()

    if all_topics or stale:
        paths = compile_all(config, stale_only=stale)
        update_index(config)
        console.print(f"[green]✓[/green] Compiled {len(paths)} wiki pages")
    elif topic:
        path = compile_topic(topic, config, force=True)
        update_index(config)
        console.print(f"[green]✓[/green] Compiled {path.name}")
    else:
        console.print("[red]Specify a topic slug or use --all[/red]")


@wiki_app.command("list")
def wiki_list() -> None:
    """List all wiki pages with confidence levels."""
    from atlas_brain.db import get_connection

    config = _get_config(require_initialized=True)
    reset_connection()
    conn = get_connection(config.db_path)

    rows = conn.execute(
        "SELECT slug, title, confidence, source_count, fact_count, last_compiled FROM wiki_pages ORDER BY title"
    ).fetchall()

    if not rows:
        console.print("[dim]No wiki pages yet.[/dim]")
        return

    table = Table(title="Wiki Pages")
    table.add_column("Slug")
    table.add_column("Title")
    table.add_column("Confidence")
    table.add_column("Sources", justify="right")
    table.add_column("Facts", justify="right")
    table.add_column("Last Compiled", style="dim")
    for r in rows:
        last = r["last_compiled"][:10] if r["last_compiled"] else "never"
        table.add_row(r["slug"], r["title"], r["confidence"],
                      str(r["source_count"]), str(r["fact_count"]), last)
    console.print(table)


# -- Session subcommands --

@session_app.command("brief")
def session_brief() -> None:
    """Generate pre-session context brief."""
    from atlas_brain.session.brief import generate_brief

    config = _get_config()
    reset_connection()
    brief = generate_brief(config)
    console.print(brief)


@session_app.command("save")
def session_save(
    summary: str = typer.Option(None, "--summary"),
    decisions: str = typer.Option(None, "--decisions", help="Comma-separated decisions"),
    actions: str = typer.Option(None, "--actions", help="Comma-separated actions"),
) -> None:
    """Save session intelligence."""
    from atlas_brain.session.save import save_session

    config = _get_config()
    reset_connection()

    dec_list = [d.strip() for d in decisions.split(",")] if decisions else None
    act_list = [a.strip() for a in actions.split(",")] if actions else None

    session_id = save_session(config, summary=summary, decisions=dec_list, actions=act_list)
    console.print(f"[green]✓[/green] Session saved: {session_id}")


# -- Serve subcommands --

@serve_app.command("mcp")
def serve_mcp() -> None:
    """Start MCP server."""
    import asyncio
    from atlas_brain.server.mcp_server import main
    console.print("[bold]Starting Atlas Brain MCP server...[/bold]")
    asyncio.run(main())


@serve_app.command("rest")
def serve_rest(
    port: int = typer.Option(7437, "--port", "-p"),
) -> None:
    """Start REST API server."""
    from atlas_brain.server.rest_api import start
    console.print(f"[bold]Starting Atlas Brain REST API on port {port}...[/bold]")
    start(port=port)


if __name__ == "__main__":
    app()
