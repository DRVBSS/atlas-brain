"""Shared input validation helpers."""

import re
from pathlib import Path

from atlas_brain.config import AtlasConfig

_TOPIC_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def resolve_path_within_root(path_value: str, config: AtlasConfig) -> Path:
    """Resolve a user path and ensure it stays inside the Atlas root."""
    raw_path = Path(path_value).expanduser()
    resolved = (
        raw_path.resolve()
        if raw_path.is_absolute()
        else (config.root / raw_path).resolve()
    )
    root = config.root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Path must stay within the Atlas root: {root}")
    return resolved


def validate_topic_slug(slug: str) -> str:
    """Reject topic slugs that could escape the wiki directory."""
    candidate = slug.strip()
    if not candidate or not _TOPIC_SLUG_RE.fullmatch(candidate):
        raise ValueError(
            "Invalid topic slug. Use letters, numbers, hyphens, and underscores only."
        )
    return candidate


def topic_title_from_slug(slug: str) -> str:
    """Convert a slug to a human-readable title."""
    return slug.replace("-", " ").replace("_", " ").strip().title()
