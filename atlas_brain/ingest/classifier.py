"""Step 1: Source type classification."""

from pathlib import Path

EXTENSION_MAP = {
    ".md": "article",
    ".txt": "article",
    ".html": "article",
    ".htm": "article",
    ".pdf": "document",
    ".docx": "document",
    ".pptx": "document",
    ".pages": "document",
    ".py": "code",
    ".js": "code",
    ".ts": "code",
    ".go": "code",
    ".rs": "code",
    ".java": "code",
    ".rb": "code",
    ".cpp": "code",
    ".c": "code",
    ".h": "code",
    ".jsx": "code",
    ".tsx": "code",
    ".swift": "code",
    ".kt": "code",
    ".sh": "code",
    ".bash": "code",
    ".zsh": "code",
    ".yaml": "code",
    ".yml": "code",
    ".toml": "code",
    ".png": "media",
    ".jpg": "media",
    ".jpeg": "media",
    ".gif": "media",
    ".webp": "media",
    ".mp3": "media",
    ".mp4": "media",
    ".wav": "media",
    ".m4a": "media",
    ".webm": "media",
    ".csv": "export",
    ".json": "_needs_content_check",
}

VALID_TYPES = {"article", "conversation", "document", "code", "meeting", "media", "export"}

# Content heuristic patterns
CONVERSATION_PATTERNS = [
    "Human:", "Assistant:", "User:", "AI:",
    '"role":', '"messages":', '"content":',
    "speaker:", "from:", "timestamp:",
]

MEETING_PATTERNS = [
    "meeting notes", "attendees:", "agenda:", "action items:",
    "minutes of", "meeting summary",
]


def classify(file_path: Path, explicit_type: str | None = None) -> str:
    """
    Determine source type from file.
    Returns one of: article, conversation, document, code, meeting, media, export
    """
    # Priority 1: explicit override
    if explicit_type:
        if explicit_type not in VALID_TYPES:
            raise ValueError(f"Invalid type '{explicit_type}'. Must be one of: {VALID_TYPES}")
        return explicit_type

    # Priority 2: extension mapping
    ext = file_path.suffix.lower()
    ext_type = EXTENSION_MAP.get(ext, "_needs_content_check")

    if ext_type != "_needs_content_check":
        return ext_type

    # Priority 3: content heuristic (read first 2000 chars)
    try:
        with open(file_path, "r", errors="replace") as f:
            head = f.read(2000).lower()
    except Exception:
        return "document"

    # Check for conversation patterns
    conversation_score = sum(1 for p in CONVERSATION_PATTERNS if p.lower() in head)
    if conversation_score >= 2:
        return "conversation"

    # Check for meeting patterns
    meeting_score = sum(1 for p in MEETING_PATTERNS if p.lower() in head)
    if meeting_score >= 2:
        return "meeting"

    # Default to document
    return "document"
