"""Shared helpers for source-level search filters."""

from atlas_brain.utils.dates import date_to_key


def normalize_filters(filters: dict | None) -> dict:
    """Drop empty filter values and keep only supported keys."""
    if not filters:
        return {}

    normalized = {}
    for key in ("source_type", "author", "date_from", "date_to"):
        value = filters.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        normalized[key] = value
    return normalized


def build_source_filter_sql(filters: dict | None, alias: str = "s") -> tuple[list[str], list]:
    """Build SQL clauses and params for source-level filters."""
    normalized = normalize_filters(filters)
    where_clauses = []
    params = []

    if "source_type" in normalized:
        where_clauses.append(f"{alias}.source_type = ?")
        params.append(normalized["source_type"])
    if "author" in normalized:
        where_clauses.append(f"{alias}.author = ?")
        params.append(normalized["author"])
    if "date_from" in normalized:
        where_clauses.append(f"{alias}.created_date >= ?")
        params.append(normalized["date_from"])
    if "date_to" in normalized:
        where_clauses.append(f"{alias}.created_date <= ?")
        params.append(normalized["date_to"])

    return where_clauses, params


def build_chroma_where(filters: dict | None) -> dict | None:
    """Build a Chroma `where` clause from normalized source filters."""
    normalized = normalize_filters(filters)
    clauses: list[dict] = []

    if "source_type" in normalized:
        clauses.append({"source_type": normalized["source_type"]})
    if "author" in normalized:
        clauses.append({"author": normalized["author"]})
    if "date_from" in normalized:
        date_key = date_to_key(normalized["date_from"])
        if date_key is not None:
            clauses.append({"created_date_key": {"$gte": date_key}})
    if "date_to" in normalized:
        date_key = date_to_key(normalized["date_to"])
        if date_key is not None:
            clauses.append({"created_date_key": {"$lte": date_key}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def matches_source_filters(row, filters: dict | None) -> bool:
    """Return whether a source-enriched row matches the active filters."""
    normalized = normalize_filters(filters)
    if not normalized:
        return True

    if "source_type" in normalized and row["source_type"] != normalized["source_type"]:
        return False
    if "author" in normalized and row["author"] != normalized["author"]:
        return False
    if "date_from" in normalized:
        created_date = row["created_date"]
        if created_date is None or created_date < normalized["date_from"]:
            return False
    if "date_to" in normalized:
        created_date = row["created_date"]
        if created_date is None or created_date > normalized["date_to"]:
            return False

    return True
