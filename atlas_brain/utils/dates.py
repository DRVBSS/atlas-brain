"""Helpers for normalizing date strings into sortable numeric keys."""

from datetime import date


def date_to_key(value: str | None) -> int | None:
    """Convert an ISO-like date string into a sortable YYYYMMDD integer."""
    if not value:
        return None

    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError:
        return None

    return (parsed.year * 10000) + (parsed.month * 100) + parsed.day
