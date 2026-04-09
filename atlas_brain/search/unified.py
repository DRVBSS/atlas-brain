"""Unified search — combines lexical, semantic, and faceted modes with RRF."""

from concurrent.futures import ThreadPoolExecutor

from atlas_brain.config import AtlasConfig
from atlas_brain.models import SearchResult
from atlas_brain.search.filters import normalize_filters
from atlas_brain.search.planner import plan_query
from atlas_brain.search.lexical import search_lexical
from atlas_brain.search.semantic import search_semantic
from atlas_brain.search.faceted import search_faceted

VALID_SEARCH_MODES = ("lexical", "semantic", "faceted")


class SearchExecutionError(RuntimeError):
    """Raised when one or more search backends fail."""

    def __init__(self, failures: dict[str, str]):
        self.failures = failures
        details = ", ".join(f"{mode}: {error}" for mode, error in failures.items())
        super().__init__(f"Search backend failure ({details})")


def normalize_search_modes(modes: list[str] | None) -> list[str] | None:
    """Normalize and validate explicit search modes."""
    if modes is None:
        return None

    normalized = []
    invalid = []
    for mode in modes:
        cleaned = mode.strip().lower()
        if not cleaned:
            continue
        if cleaned not in VALID_SEARCH_MODES:
            invalid.append(mode)
            continue
        if cleaned not in normalized:
            normalized.append(cleaned)

    if invalid:
        allowed = ", ".join(VALID_SEARCH_MODES)
        bad = ", ".join(invalid)
        raise ValueError(f"Unknown search mode(s): {bad}. Allowed modes: {allowed}.")

    if not normalized:
        allowed = ", ".join(VALID_SEARCH_MODES)
        raise ValueError(f"No valid search modes provided. Allowed modes: {allowed}.")

    return normalized


def _reciprocal_rank_fusion(
    result_lists: list[list[SearchResult]], k: int = 60
) -> list[SearchResult]:
    """Merge results using Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    results_by_id: dict[str, SearchResult] = {}

    for result_list in result_lists:
        for rank, result in enumerate(result_list):
            cid = result.chunk_id
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            if cid not in results_by_id:
                results_by_id[cid] = result

    # Sort by fused score
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    merged = []
    for cid in sorted_ids:
        result = results_by_id[cid]
        result.relevance_score = scores[cid]
        merged.append(result)

    return merged


def search(
    query: str,
    config: AtlasConfig,
    modes: list[str] | None = None,
    filters: dict | None = None,
    top_k: int = 10,
) -> list[SearchResult]:
    """
    Unified search across all modes.
    1. Run query planner if modes not specified
    2. Execute each mode in parallel
    3. Merge results with RRF
    4. Return top-K, or raise SearchExecutionError if any mode fails
    """
    normalized_filters = normalize_filters(filters)
    modes = normalize_search_modes(modes)

    if modes is None:
        plan = plan_query(query, filters=normalized_filters)
        modes = plan.modes
        if not normalized_filters:
            filters = plan.filters
            normalized_filters = filters
    else:
        filters = normalized_filters

    result_lists = []
    failures: dict[str, str] = {}

    mode_funcs = {
        "lexical": lambda: search_lexical(query, config, filters=normalized_filters, limit=top_k * 3),
        "semantic": lambda: search_semantic(query, config, filters=normalized_filters, limit=top_k * 3),
        "faceted": lambda: search_faceted(query, config, filters=normalized_filters, limit=top_k * 3),
    }

    # Run modes in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for mode in modes:
            if mode in mode_funcs:
                futures[mode] = executor.submit(mode_funcs[mode])

        for mode, future in futures.items():
            try:
                results = future.result()
                if results:
                    result_lists.append(results)
            except Exception as e:
                failures[mode] = str(e) or e.__class__.__name__

    if failures:
        raise SearchExecutionError(failures)

    if not result_lists:
        return []

    # RRF merge
    merged = _reciprocal_rank_fusion(result_lists)

    return merged[:top_k]
