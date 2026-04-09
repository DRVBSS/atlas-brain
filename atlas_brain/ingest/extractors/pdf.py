"""PDF text extraction via pdfplumber."""

import logging
from pathlib import Path

from atlas_brain.models import ProcessedDocument

logger = logging.getLogger(__name__)


def extract(file_path: Path) -> ProcessedDocument:
    """Extract text from PDF files using pdfplumber."""
    import pdfplumber

    pages_text = []
    title = None
    metadata = {}

    with pdfplumber.open(file_path) as pdf:
        metadata["page_count"] = len(pdf.pages)

        # Try to get title from PDF metadata
        if pdf.metadata:
            title = pdf.metadata.get("Title") or pdf.metadata.get("title")
            author = pdf.metadata.get("Author") or pdf.metadata.get("author")
            if author:
                metadata["author"] = author

        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:
                pages_text.append(text)

            # Try tables too
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row:
                        pages_text.append(" | ".join(str(cell or "") for cell in row))

    full_text = "\n\n".join(pages_text)

    if not full_text.strip():
        logger.warning(f"No text extracted from PDF: {file_path}. May need OCR.")
        full_text = f"[No text extracted from {file_path.name}. PDF may be image-based and require OCR.]"

    if not title:
        # Use first line as title fallback
        first_line = full_text.split("\n")[0].strip() if full_text.strip() else file_path.stem
        title = first_line[:100] if first_line else file_path.stem

    word_count = len(full_text.split())

    return ProcessedDocument(
        text=full_text,
        title=title,
        author=metadata.get("author"),
        created_date=None,
        word_count=word_count,
        sections=[],
        metadata=metadata,
    )
