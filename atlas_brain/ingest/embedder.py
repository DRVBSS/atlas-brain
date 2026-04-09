"""Step 6: Embedding generation via sentence-transformers + ChromaDB."""

import logging
import threading

from atlas_brain.models import Chunk
from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.utils.dates import date_to_key

logger = logging.getLogger(__name__)

_chroma_client = None
_embed_model = None
_embed_model_lock = threading.Lock()
_chroma_client_lock = threading.Lock()

DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5"
COLLECTION_NAME = "atlas_chunks"
EMBEDDING_METADATA_VERSION = 2


def _get_embed_model():
    """Lazy-load the sentence-transformers model."""
    global _embed_model
    if _embed_model is None:
        with _embed_model_lock:
            if _embed_model is None:
                from sentence_transformers import SentenceTransformer

                logger.info(f"Loading embedding model: {DEFAULT_MODEL}")
                _embed_model = SentenceTransformer(DEFAULT_MODEL, trust_remote_code=True)
    return _embed_model


def _get_chroma_collection(config: AtlasConfig):
    """Get or create the ChromaDB collection."""
    global _chroma_client
    if _chroma_client is None:
        with _chroma_client_lock:
            if _chroma_client is None:
                import chromadb

                config.chroma_dir.mkdir(parents=True, exist_ok=True)
                _chroma_client = chromadb.PersistentClient(path=str(config.chroma_dir))
    return _chroma_client.get_or_create_collection(name=COLLECTION_NAME)


def _get_collection_metadata_version(collection) -> int:
    """Return the embedding metadata version stored on the collection."""
    metadata = collection.metadata or {}
    try:
        return int(metadata.get("atlas_embedding_metadata_version", 0))
    except (TypeError, ValueError):
        return 0


def _set_collection_metadata_version(collection, version: int) -> None:
    """Persist the embedding metadata version on the collection."""
    metadata = dict(collection.metadata or {})
    metadata["atlas_embedding_metadata_version"] = version
    collection.modify(metadata=metadata)


def _build_embedding_metadata(
    chunk: Chunk,
    source_type: str | None,
    author: str | None,
    created_date: str | None,
) -> dict:
    """Build Chroma metadata for a chunk with filterable source fields."""
    metadata = {
        "source_id": chunk.source_id,
        "chunk_index": chunk.chunk_index,
        "section_heading": chunk.section_heading or "",
        "speaker": chunk.speaker or "",
    }
    if source_type:
        metadata["source_type"] = source_type
    if author:
        metadata["author"] = author
    if created_date:
        metadata["created_date"] = created_date
        created_date_key = date_to_key(created_date)
        if created_date_key is not None:
            metadata["created_date_key"] = created_date_key
    return metadata


def ensure_embedding_metadata(config: AtlasConfig, force: bool = False) -> int:
    """Backfill richer source metadata onto existing Chroma embeddings."""
    collection = _get_chroma_collection(config)
    if collection.count() == 0:
        return 0

    current_version = _get_collection_metadata_version(collection)
    if not force and current_version >= EMBEDDING_METADATA_VERSION:
        return 0

    conn = get_connection(config.db_path)
    rows = conn.execute(
        """SELECT c.chunk_id, c.source_id, c.chunk_index, c.section_heading, c.speaker,
                  s.source_type, s.author, s.created_date
           FROM chunks c
           JOIN sources s ON c.source_id = s.source_id
           WHERE c.embedding_id IS NOT NULL"""
    ).fetchall()

    if not rows:
        _set_collection_metadata_version(collection, EMBEDDING_METADATA_VERSION)
        return 0

    batch_size = 500
    updated = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        ids = [row["chunk_id"] for row in batch]
        metadatas = [
            _build_embedding_metadata(
                Chunk(
                    chunk_id=row["chunk_id"],
                    source_id=row["source_id"],
                    chunk_index=row["chunk_index"],
                    content="",
                    section_heading=row["section_heading"],
                    speaker=row["speaker"],
                ),
                row["source_type"],
                row["author"],
                row["created_date"],
            )
            for row in batch
        ]
        collection.update(ids=ids, metadatas=metadatas)
        updated += len(batch)

    _set_collection_metadata_version(collection, EMBEDDING_METADATA_VERSION)
    return updated


def generate_embeddings(chunks: list[Chunk], config: AtlasConfig) -> None:
    """Generate embeddings for chunks and store in ChromaDB."""
    if not chunks:
        return

    model = _get_embed_model()
    collection = _get_chroma_collection(config)
    existing_count = collection.count()
    current_version = _get_collection_metadata_version(collection)
    conn = get_connection(config.db_path)

    source_ids = sorted({ch.source_id for ch in chunks})
    source_rows = {}
    if source_ids:
        placeholders = ",".join("?" for _ in source_ids)
        rows = conn.execute(
            f"""SELECT source_id, source_type, author, created_date
                FROM sources
                WHERE source_id IN ({placeholders})""",
            source_ids,
        ).fetchall()
        source_rows = {row["source_id"]: row for row in rows}

    # Prepare texts — prefix section heading if present
    texts = []
    ids = []
    metadatas = []
    for ch in chunks:
        text = ch.content
        if ch.section_heading:
            text = f"{ch.section_heading}: {text}"
        texts.append(text)
        ids.append(ch.chunk_id)
        source_row = source_rows.get(ch.source_id)
        metadatas.append(
            _build_embedding_metadata(
                ch,
                source_row["source_type"] if source_row else None,
                source_row["author"] if source_row else None,
                source_row["created_date"] if source_row else None,
            )
        )

    # Generate embeddings
    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    # Store in ChromaDB
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )

    # Update chunk records with embedding_id
    for ch in chunks:
        conn.execute(
            "UPDATE chunks SET embedding_id = ? WHERE chunk_id = ?",
            (ch.chunk_id, ch.chunk_id),
        )
    conn.commit()

    # Mark the collection current only when all stored embeddings are known to carry the new metadata.
    if existing_count == 0 or current_version >= EMBEDDING_METADATA_VERSION:
        _set_collection_metadata_version(collection, EMBEDDING_METADATA_VERSION)
