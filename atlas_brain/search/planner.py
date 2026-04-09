"""Query classification and routing."""

import re
from dataclasses import dataclass, field

from atlas_brain.search.filters import normalize_filters


@dataclass
class QueryPlan:
    modes: list[str] = field(default_factory=lambda: ["lexical", "semantic"])
    filters: dict = field(default_factory=dict)
    sort: str = "relevance"


def plan_query(query: str, explicit_mode: str | None = None, filters: dict | None = None) -> QueryPlan:
    """
    Classify the query to decide which search modes to use.

    Heuristics:
    - Empty query plus real filters → browse via faceted mode
    - Normal keyword/text queries → lexical + semantic
    - Internal IDs → lexical only
    """
    if explicit_mode:
        return QueryPlan(
            modes=[explicit_mode],
            filters=normalize_filters(filters),
        )

    normalized_filters = normalize_filters(filters)
    query = query.strip()

    if not query and normalized_filters:
        return QueryPlan(
            modes=["faceted"],
            filters=normalized_filters,
            sort="date",
        )

    modes = []

    # Question words → semantic
    is_question = any(
        query.lower().startswith(w) for w in
        ["what", "how", "why", "when", "where", "who", "which", "explain", "describe"]
    )

    # Date patterns influence sort order
    has_date = re.search(r'\d{4}-\d{2}-\d{2}|\d{4}', query) is not None

    # Lexical always runs — keyword matches should never be missed
    modes.append("lexical")

    # Semantic runs for most queries (conceptual, open-ended, or general keywords)
    if is_question or not re.search(r'src_\w+|chk_\w+|fct_\w+', query):
        modes.append("semantic")

    return QueryPlan(
        modes=modes,
        filters=normalized_filters,
        sort="date" if has_date else "relevance",
    )
