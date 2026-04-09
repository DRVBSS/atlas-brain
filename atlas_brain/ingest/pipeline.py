"""Main ingest orchestrator — 9-step pipeline."""

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.models import IngestResult
from atlas_brain.ingest.classifier import classify
from atlas_brain.ingest.archiver import archive, move_to_processed, DuplicateSourceError
from atlas_brain.ingest.extractors import get_extractor
from atlas_brain.ingest.chunker import chunk
from atlas_brain.ingest.logger import log_ingest
from atlas_brain.utils.ids import generate_id


def _embeddings_enabled(skip_embeddings: bool) -> bool:
    """Allow callers or env vars to skip expensive embedding generation."""
    if skip_embeddings:
        return False
    raw = os.environ.get("ATLAS_SKIP_EMBEDDINGS", "").strip().lower()
    return raw not in {"1", "true", "yes", "on"}


def write_processed(source_id: str, processed_doc, config: AtlasConfig) -> Path:
    """Write extracted text to processed/{source_id}.md."""
    config.processed_dir.mkdir(parents=True, exist_ok=True)
    out_path = config.processed_dir / f"{source_id}.md"
    out_path.write_text(processed_doc.text)
    return out_path


def create_manifest(
    source_id: str,
    archived_path: Path,
    processed_doc,
    source_type: str,
    content_hash: str,
    config: AtlasConfig,
) -> None:
    """Insert source record into SQLite."""
    conn = get_connection(config.db_path)
    processed_path = str(config.processed_dir / f"{source_id}.md")

    # Simple keyword-based topic/people/project detection
    text_lower = processed_doc.text.lower()
    metadata = processed_doc.metadata.copy()

    conn.execute(
        """INSERT INTO sources
           (source_id, original_path, processed_path, source_type, content_hash,
            title, author, created_date, ingested_at, word_count, language, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source_id,
            str(archived_path),
            processed_path,
            source_type,
            content_hash,
            processed_doc.title,
            processed_doc.author,
            processed_doc.created_date,
            datetime.now(timezone.utc).isoformat(),
            processed_doc.word_count,
            "en",
            json.dumps(metadata) if metadata else None,
        ),
    )
    # No commit here — caller manages the transaction


def save_chunks(chunks: list, config: AtlasConfig) -> None:
    """Insert chunks into the database."""
    conn = get_connection(config.db_path)
    for ch in chunks:
        conn.execute(
            """INSERT INTO chunks
               (chunk_id, source_id, chunk_index, content, section_heading, speaker, token_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ch.chunk_id, ch.source_id, ch.chunk_index, ch.content,
             ch.section_heading, ch.speaker, ch.token_count),
        )
    # No commit here — caller manages the transaction


def ingest_file(
    file_path: Path,
    config: AtlasConfig,
    explicit_type: str | None = None,
    skip_embeddings: bool = False,
) -> IngestResult:
    """Run the full pipeline on a single file."""
    start = time.time()
    steps_completed = []
    errors = []
    source_id = ""
    archived_path = None

    try:
        # Step 1: Classify
        source_type = classify(file_path, explicit_type)
        steps_completed.append("classify")

        # Step 2: Archive (dedup check happens here)
        source_id, archived_path, content_hash = archive(file_path, source_type, config)
        steps_completed.append("archive")

        # Steps 3-5 in a single transaction — rollback on failure
        conn = get_connection(config.db_path)
        try:
            # Step 3: Extract
            extractor = get_extractor(archived_path, source_type)
            processed_doc = extractor(archived_path)
            write_processed(source_id, processed_doc, config)
            steps_completed.append("extract")

            # Step 4: Manifest (no individual commit)
            create_manifest(source_id, archived_path, processed_doc, source_type, content_hash, config)
            steps_completed.append("manifest")

            # Step 5: Chunk (no individual commit)
            chunks = chunk(processed_doc.text, source_type, source_id)
            save_chunks(chunks, config)
            steps_completed.append("chunk")

            # Commit all sequential steps together
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        # Steps 6, 7, 8: run in parallel
        from concurrent.futures import ThreadPoolExecutor
        from atlas_brain.ingest.embedder import generate_embeddings
        from atlas_brain.ingest.indexer import index_fts
        from atlas_brain.ingest.fact_extractor import extract_facts as _extract_facts

        worker_specs = [
            ("fts", lambda: index_fts(chunks, config)),
            ("facts", lambda: _extract_facts(processed_doc.text, source_id, config)),
        ]
        if _embeddings_enabled(skip_embeddings):
            worker_specs.insert(0, ("embed", lambda: generate_embeddings(chunks, config)))
        else:
            steps_completed.append("embed_skipped")

        with ThreadPoolExecutor(max_workers=len(worker_specs)) as executor:
            futures = [
                (name, executor.submit(fn))
                for name, fn in worker_specs
            ]

            for name, future in futures:
                try:
                    future.result()
                    steps_completed.append(name)
                except Exception as e:
                    errors.append({"step": name, "error": str(e)})

        # Auto-promote corroborated and well-formed facts
        _run_auto_promotion(steps_completed, errors, config, source_id=source_id)

        # Step 9: Log
        duration = time.time() - start
        status = "success" if not errors else "partial"
        log_ingest(source_id, status, steps_completed, errors, duration, config)

        return IngestResult(
            source_id=source_id,
            status=status,
            errors=errors,
            steps_completed=steps_completed,
            duration_ms=int(duration * 1000),
        )

    except DuplicateSourceError as e:
        raise
    except Exception as e:
        duration = time.time() - start
        errors.append({"step": steps_completed[-1] if steps_completed else "init", "error": str(e)})
        # Clean up orphaned archived file if pipeline failed after archive
        if archived_path and archived_path.exists():
            archived_path.unlink(missing_ok=True)
        # Clean up processed file
        processed_path = config.processed_dir / f"{source_id}.md"
        if processed_path.exists():
            processed_path.unlink(missing_ok=True)
        if source_id:
            log_ingest(source_id, "failed", steps_completed, errors, duration, config)
        return IngestResult(
            source_id=source_id,
            status="failed",
            errors=errors,
            steps_completed=steps_completed,
            duration_ms=int(duration * 1000),
        )


def _run_auto_promotion(steps_completed: list, errors: list, config: AtlasConfig, source_id: str | None = None) -> None:
    """Auto-promote corroborated and well-formed fact candidates, then detect contradictions.

    When source_id is provided, only processes candidates from that source
    (incremental mode). Otherwise processes all pending candidates (full mode).
    """
    from atlas_brain.knowledge.facts import auto_promote_corroborated, auto_promote_single_source
    from atlas_brain.knowledge.contradictions import detect_contradictions

    try:
        promoted = auto_promote_corroborated(config, source_id=source_id)
        promoted += auto_promote_single_source(config, source_id=source_id)
        if promoted:
            steps_completed.append(f"auto_promote({len(promoted)})")
        new_contras = detect_contradictions(config, source_id=source_id)
        if new_contras:
            steps_completed.append(f"contradictions({len(new_contras)})")
    except Exception as e:
        errors.append({"step": "auto_promote", "error": str(e)})


def ingest_directory(
    dir_path: Path,
    config: AtlasConfig,
    skip_embeddings: bool = False,
) -> list[IngestResult]:
    """Ingest all files in a directory (typically inbox/)."""
    results = []
    for file_path in sorted(dir_path.iterdir()):
        if file_path.is_file() and not file_path.name.startswith('.'):
            try:
                result = ingest_file(file_path, config, skip_embeddings=skip_embeddings)
                results.append(result)
                # Move processed file to inbox/.processed/
                move_to_processed(file_path, config)
            except DuplicateSourceError:
                move_to_processed(file_path, config)
    return results


def ingest_recall_export(
    zip_path: Path,
    config: AtlasConfig,
    skip_embeddings: bool = False,
) -> list[IngestResult]:
    """
    Ingest a Recall (getrecall.ai) ZIP export.
    Extracts the ZIP, parses each markdown knowledge card with its
    YAML frontmatter (tags, URL, categories), and ingests through
    the standard pipeline using the Recall-specific extractor.
    """
    from atlas_brain.ingest.extractors.recall import extract_recall_zip, extract as recall_extract, cleanup_temp

    md_files = extract_recall_zip(zip_path)
    if not md_files:
        return []

    results = []
    try:
        for md_path, frontmatter in md_files:
            try:
                # Use the standard pipeline but force article type and Recall extractor
                result = _ingest_recall_card(
                    md_path,
                    frontmatter,
                    config,
                    recall_extract,
                    skip_embeddings=skip_embeddings,
                )
                results.append(result)
            except DuplicateSourceError:
                pass
    finally:
        cleanup_temp(md_files)

    return results


def _ingest_recall_card(
    file_path: Path,
    frontmatter: dict,
    config: AtlasConfig,
    recall_extract,
    skip_embeddings: bool = False,
) -> IngestResult:
    """Ingest a single Recall knowledge card through the pipeline."""
    start = time.time()
    steps_completed = []
    errors = []
    source_id = ""
    archived_path = None

    try:
        # Step 1: Always classify as article (Recall cards are articles)
        source_type = "article"
        steps_completed.append("classify")

        # Step 2: Archive
        source_id, archived_path, content_hash = archive(file_path, source_type, config)
        steps_completed.append("archive")

        # Steps 3-5 in a single transaction (same pattern as ingest_file)
        conn = get_connection(config.db_path)
        try:
            # Step 3: Extract using Recall-specific extractor
            processed_doc = recall_extract(archived_path)
            write_processed(source_id, processed_doc, config)
            steps_completed.append("extract")

            # Step 4: Manifest
            create_manifest(source_id, archived_path, processed_doc, source_type, content_hash, config)
            steps_completed.append("manifest")

            # Step 5: Chunk
            chunks = chunk(processed_doc.text, source_type, source_id)
            save_chunks(chunks, config)
            steps_completed.append("chunk")

            # Commit so parallel workers on separate connections can see these rows
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        # Steps 6, 7, 8: parallel
        from concurrent.futures import ThreadPoolExecutor
        from atlas_brain.ingest.embedder import generate_embeddings
        from atlas_brain.ingest.indexer import index_fts
        from atlas_brain.ingest.fact_extractor import extract_facts as _extract_facts

        worker_specs = [
            ("fts", lambda: index_fts(chunks, config)),
            ("facts", lambda: _extract_facts(processed_doc.text, source_id, config)),
        ]
        if _embeddings_enabled(skip_embeddings):
            worker_specs.insert(0, ("embed", lambda: generate_embeddings(chunks, config)))
        else:
            steps_completed.append("embed_skipped")

        with ThreadPoolExecutor(max_workers=len(worker_specs)) as executor:
            futures = [
                (name, executor.submit(fn))
                for name, fn in worker_specs
            ]

            for name, future in futures:
                try:
                    future.result()
                    steps_completed.append(name)
                except Exception as e:
                    errors.append({"step": name, "error": str(e)})

        # Auto-promote corroborated and well-formed facts
        _run_auto_promotion(steps_completed, errors, config, source_id=source_id)

        # Step 9: Log
        duration = time.time() - start
        status = "success" if not errors else "partial"
        log_ingest(source_id, status, steps_completed, errors, duration, config)

        return IngestResult(
            source_id=source_id,
            status=status,
            errors=errors,
            steps_completed=steps_completed,
            duration_ms=int(duration * 1000),
        )

    except DuplicateSourceError:
        raise
    except Exception as e:
        duration = time.time() - start
        errors.append({"step": steps_completed[-1] if steps_completed else "init", "error": str(e)})
        if archived_path and archived_path.exists():
            archived_path.unlink(missing_ok=True)
        processed_path = config.processed_dir / f"{source_id}.md"
        if processed_path.exists():
            processed_path.unlink(missing_ok=True)
        if source_id:
            log_ingest(source_id, "failed", steps_completed, errors, duration, config)
        return IngestResult(
            source_id=source_id,
            status="failed",
            errors=errors,
            steps_completed=steps_completed,
            duration_ms=int(duration * 1000),
        )
