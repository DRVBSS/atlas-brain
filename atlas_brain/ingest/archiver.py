"""Step 2: Sovereign archive — copy to sources/, hash, dedup."""

import re
import shutil
from pathlib import Path

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.utils.ids import generate_id
from atlas_brain.utils.hashing import sha256_file


class DuplicateSourceError(Exception):
    """Raised when a file with the same content hash already exists."""
    pass


# Map source types to directory names
TYPE_TO_DIR = {
    "article": "articles",
    "conversation": "conversations",
    "document": "documents",
    "code": "code",
    "meeting": "meetings",
    "media": "media",
    "export": "exports",
}


def sanitize_filename(name: str) -> str:
    """Remove characters that are problematic in filenames."""
    name = re.sub(r'[^\w\s\-.]', '', name)
    name = re.sub(r'\s+', '_', name)
    return name[:100]


def archive(file_path: Path, source_type: str, config: AtlasConfig) -> tuple[str, Path, str]:
    """
    Copy original to sources/{type}/, generate source_id, compute hash.
    Returns (source_id, archived_path, content_hash).
    Raises DuplicateSourceError if content_hash already exists.
    """
    content_hash = sha256_file(file_path)

    # Check for duplicate
    conn = get_connection(config.db_path)
    row = conn.execute(
        "SELECT source_id FROM sources WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    if row:
        raise DuplicateSourceError(
            f"File already ingested as {row['source_id']}"
        )

    source_id = generate_id("src")
    dir_name = TYPE_TO_DIR.get(source_type, "documents")
    dest_dir = config.sources_dir / dir_name
    dest_dir.mkdir(parents=True, exist_ok=True)

    sanitized_name = sanitize_filename(file_path.stem)
    dest = dest_dir / f"{source_id}_{sanitized_name}{file_path.suffix}"

    shutil.copy2(file_path, dest)

    return source_id, dest, content_hash


def move_to_processed(file_path: Path, config: AtlasConfig) -> None:
    """Move original from inbox/ to inbox/.processed/."""
    inbox = config.inbox_dir
    if not str(file_path.resolve()).startswith(str(inbox.resolve())):
        return  # Not in inbox, skip

    processed_dir = inbox / ".processed"
    processed_dir.mkdir(exist_ok=True)
    dest = processed_dir / file_path.name
    if dest.exists():
        dest = processed_dir / f"{file_path.stem}_{generate_id('dup')}{file_path.suffix}"
    shutil.move(str(file_path), str(dest))
