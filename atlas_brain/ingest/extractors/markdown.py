"""Markdown / plain text extractor."""

import re
from pathlib import Path

from atlas_brain.models import ProcessedDocument


def extract(file_path: Path) -> ProcessedDocument:
    """Extract text from markdown or plain text files."""
    text = file_path.read_text(errors="replace")

    # Clean up whitespace
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # Extract title from first heading
    title = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            title = line.lstrip("# ").strip()
            break
        elif line and not line.startswith("#"):
            # First non-empty, non-heading line as fallback
            if title is None:
                title = line[:100]
            break

    if title is None:
        title = file_path.stem

    # Extract section headings
    sections = []
    for line in text.splitlines():
        line = line.strip()
        if re.match(r'^#{1,6}\s+', line):
            heading = re.sub(r'^#+\s+', '', line)
            sections.append(heading)

    # Detect author (look for common patterns)
    author = None
    author_patterns = [
        r'(?:author|by|written by)[:\s]+(.+?)(?:\n|$)',
        r'@(\w+)',
    ]
    for pattern in author_patterns:
        match = re.search(pattern, text[:500], re.IGNORECASE)
        if match:
            author = match.group(1).strip()
            break

    # Detect date
    created_date = None
    date_patterns = [
        r'(?:date|published|created)[:\s]+(\d{4}-\d{2}-\d{2})',
        r'(\d{4}-\d{2}-\d{2})',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text[:500])
        if match:
            created_date = match.group(1)
            break

    word_count = len(text.split())

    return ProcessedDocument(
        text=text,
        title=title,
        author=author,
        created_date=created_date,
        word_count=word_count,
        sections=sections,
        metadata={},
    )
