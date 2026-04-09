"""URL fetch and HTML-to-markdown conversion."""

import logging
from pathlib import Path

from atlas_brain.models import ProcessedDocument

logger = logging.getLogger(__name__)


def fetch_and_extract(url: str) -> ProcessedDocument:
    """Fetch a URL and convert HTML to markdown."""
    import httpx
    from markitdown import MarkItDown

    response = httpx.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()

    # Write to temp file for markitdown
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w") as f:
        f.write(response.text)
        tmp_path = Path(f.name)

    try:
        md = MarkItDown()
        result = md.convert(str(tmp_path))
        text = result.text_content if result.text_content else response.text
    except Exception as e:
        logger.warning(f"markitdown conversion failed: {e}, using raw text")
        text = response.text
    finally:
        tmp_path.unlink(missing_ok=True)

    # Extract title from HTML
    title = None
    import re
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', response.text, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()

    if not title:
        title = url.split("/")[-1] or url

    return ProcessedDocument(
        text=text,
        title=title,
        word_count=len(text.split()),
        metadata={"url_origin": url, "status_code": response.status_code},
    )


def extract(file_path: Path) -> ProcessedDocument:
    """Extract from a local HTML file."""
    from markitdown import MarkItDown

    try:
        md = MarkItDown()
        result = md.convert(str(file_path))
        text = result.text_content if result.text_content else file_path.read_text(errors="replace")
    except Exception:
        text = file_path.read_text(errors="replace")

    import re
    title = None
    raw = file_path.read_text(errors="replace")
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', raw, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()

    if not title:
        title = file_path.stem

    return ProcessedDocument(
        text=text,
        title=title,
        word_count=len(text.split()),
        sections=[],
        metadata={},
    )
