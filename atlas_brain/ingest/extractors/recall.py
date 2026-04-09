"""Recall (getrecall.ai) knowledge card extractor.

Recall exports knowledge bases as ZIP files containing markdown files
with YAML frontmatter. This extractor handles:
- ZIP extraction
- YAML frontmatter parsing (tags, URL, title, date, categories)
- Markdown content extraction with Recall-specific metadata
"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from atlas_brain.models import ProcessedDocument


def extract_recall_zip(zip_path: Path) -> list[tuple[Path, dict]]:
    """
    Extract a Recall ZIP export to a temp directory.
    Returns list of (markdown_file_path, frontmatter_dict) tuples.
    """
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"Not a valid ZIP file: {zip_path}")

    temp_dir = Path(tempfile.mkdtemp(prefix="atlas_recall_"))
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(temp_dir)

    # Find all markdown files in the extracted content
    md_files = []
    for md_path in sorted(temp_dir.rglob("*.md")):
        if md_path.is_file():
            frontmatter = _parse_frontmatter(md_path)
            md_files.append((md_path, frontmatter))

    return md_files


def cleanup_temp(md_files: list[tuple[Path, dict]]) -> None:
    """Remove temp directory after ingestion."""
    if md_files:
        temp_root = md_files[0][0].parent
        # Walk up to find the temp directory root
        while temp_root.parent != temp_root and "atlas_recall_" not in temp_root.name:
            temp_root = temp_root.parent
        if "atlas_recall_" in temp_root.name:
            shutil.rmtree(temp_root, ignore_errors=True)


def extract(file_path: Path) -> ProcessedDocument:
    """Extract a single Recall markdown knowledge card."""
    text = file_path.read_text(errors="replace")
    frontmatter = _parse_frontmatter(file_path)

    # Separate frontmatter from body
    body = _strip_frontmatter(text)

    # Build metadata from frontmatter
    metadata = {"source_app": "recall"}

    title = frontmatter.get("title") or _extract_first_heading(body) or file_path.stem
    author = frontmatter.get("author")
    created_date = frontmatter.get("created") or frontmatter.get("date")
    url_origin = frontmatter.get("url") or frontmatter.get("source") or frontmatter.get("link")

    # Tags — Recall uses nested tags like "parent/child"
    tags = frontmatter.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    metadata["recall_tags"] = tags

    # Categories
    categories = frontmatter.get("categories") or frontmatter.get("category")
    if categories:
        if isinstance(categories, str):
            categories = [categories]
        metadata["recall_categories"] = categories

    if url_origin:
        metadata["url_origin"] = url_origin

    # Preserve any other frontmatter fields
    for key, value in frontmatter.items():
        if key not in ("title", "author", "created", "date", "url", "source",
                       "link", "tags", "categories", "category"):
            metadata[f"recall_{key}"] = value

    # Extract section headings from body
    sections = re.findall(r'^#{1,6}\s+(.+)$', body, re.MULTILINE)

    word_count = len(body.split())

    return ProcessedDocument(
        text=body,
        title=title,
        author=author,
        created_date=str(created_date) if created_date else None,
        word_count=word_count,
        sections=sections,
        metadata=metadata,
    )


def _parse_frontmatter(file_path: Path) -> dict:
    """Parse YAML frontmatter from a markdown file."""
    text = file_path.read_text(errors="replace")

    # Check for YAML frontmatter delimiters
    if not text.startswith("---"):
        return {}

    # Find closing delimiter
    end = text.find("---", 3)
    if end == -1:
        return {}

    frontmatter_text = text[3:end].strip()

    # Parse simple YAML (avoid full yaml dependency)
    result = {}
    current_key = None
    list_values = []

    for line in frontmatter_text.splitlines():
        line_stripped = line.strip()

        if not line_stripped or line_stripped.startswith("#"):
            continue

        # Check for list item (continuation of previous key)
        if line_stripped.startswith("- ") and current_key:
            list_values.append(line_stripped[2:].strip().strip("'\""))
            result[current_key] = list_values
            continue

        # Key-value pair
        if ":" in line_stripped:
            if current_key and list_values:
                result[current_key] = list_values

            key, _, value = line_stripped.partition(":")
            key = key.strip()
            value = value.strip().strip("'\"")
            current_key = key
            list_values = []

            if value:
                # Check for inline list: [tag1, tag2]
                if value.startswith("[") and value.endswith("]"):
                    items = value[1:-1].split(",")
                    result[key] = [i.strip().strip("'\"") for i in items if i.strip()]
                else:
                    result[key] = value
            # If no value, might be followed by list items

    if current_key and list_values:
        result[current_key] = list_values

    return result


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from markdown text."""
    if not text.startswith("---"):
        return text

    end = text.find("---", 3)
    if end == -1:
        return text

    return text[end + 3:].strip()


def _extract_first_heading(text: str) -> str | None:
    """Extract the first markdown heading."""
    match = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
    return match.group(1).strip() if match else None
