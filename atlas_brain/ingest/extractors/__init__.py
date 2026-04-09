"""Extractor dispatch — maps source type + extension to extractor."""

from pathlib import Path
from typing import Protocol

from atlas_brain.models import ProcessedDocument


class ExternalExtractor(Protocol):
    """Interface for MCP-backed extraction plugins."""

    def can_handle(self, file_path: Path, source_type: str) -> bool: ...
    def extract(self, file_path: Path, source_id: str, config: dict) -> ProcessedDocument: ...

    @property
    def mcp_server_name(self) -> str: ...


def get_extractor(file_path: Path, source_type: str):
    """Return the appropriate extraction function for a file."""
    ext = file_path.suffix.lower()

    if source_type == "article" or ext in (".md", ".txt", ".html", ".htm"):
        from atlas_brain.ingest.extractors.markdown import extract
        return extract

    if source_type == "document":
        if ext == ".pdf":
            from atlas_brain.ingest.extractors.pdf import extract
            return extract
        if ext == ".docx":
            from atlas_brain.ingest.extractors.docx import extract
            return extract
        if ext == ".pptx":
            from atlas_brain.ingest.extractors.pptx import extract
            return extract
        # Fallback to markdown for other document types
        from atlas_brain.ingest.extractors.markdown import extract
        return extract

    if source_type == "code":
        from atlas_brain.ingest.extractors.code import extract
        return extract

    if source_type == "conversation":
        from atlas_brain.ingest.extractors.conversation import extract
        return extract

    if source_type == "media":
        from atlas_brain.ingest.extractors.media import extract
        return extract

    # Default fallback: treat as markdown/text
    from atlas_brain.ingest.extractors.markdown import extract
    return extract
