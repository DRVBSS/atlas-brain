"""Step 8: AI fact candidate extraction via LLM."""

import json
import logging
import os
from datetime import datetime, timezone

from atlas_brain.config import AtlasConfig
from atlas_brain.db import get_connection
from atlas_brain.models import FactCandidate
from atlas_brain.utils.ids import generate_id

logger = logging.getLogger(__name__)
DEFAULT_LLM_TIMEOUT_SECONDS = 120.0

EXTRACTION_PROMPT = """Read the following source material and extract factual claims as structured triples.

For each fact, provide:
- subject: the entity or topic the fact is about
- predicate: the relationship or property
- object: the value or target entity
- valid_from: ISO date if mentioned or inferrable, otherwise null
- valid_to: ISO date if mentioned, otherwise null

Only extract claims explicitly stated or strongly implied by the text.
Do not infer beyond what the text supports.
If a date is not clear, leave it null.
Return as JSON array.

Source [{source_id}]:
{processed_text}"""


def _detect_model() -> tuple[str, str | None]:
    """
    Auto-detect which LLM backend is available.
    Priority: explicit override → msty.ai (free, local) → Ollama → paid APIs.
    Returns (model_string, base_url_override).
    """
    import os
    import httpx

    # 1. Explicit override
    configured = os.environ.get("ATLAS_LLM_MODEL")
    if configured:
        return configured, os.environ.get("OPENAI_BASE_URL")

    # 2. msty.ai — free, local, default port: 10000
    for port in [10000]:
        try:
            r = httpx.get(f"http://localhost:{port}/v1/models", timeout=2)
            if r.status_code == 200:
                models = r.json().get("data", [])
                preferred = "mlx-community/Qwen2.5-72B-Instruct-8bit"
                available_ids = [m["id"] for m in models]
                model_id = preferred if preferred in available_ids else (available_ids[0] if available_ids else "default")
                base_url = f"http://localhost:{port}/v1"
                logger.info(f"Using msty.ai on port {port}, model: {model_id}")
                return f"openai:{model_id}", base_url
        except Exception:
            pass

    # 3. Ollama — free, local
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            models = r.json().get("models", [])
            if models:
                return f"ollama:{models[0]['name']}", None
    except Exception:
        pass

    # 4. llama.cpp server — free, local
    llama_port = int(os.environ.get("LLAMA_CPP_PORT", "8080"))
    try:
        r = httpx.get(f"http://localhost:{llama_port}/v1/models", timeout=2)
        if r.status_code == 200:
            models = r.json().get("data", [])
            model_id = models[0]["id"] if models else "default"
            base_url = f"http://localhost:{llama_port}/v1"
            logger.info(f"Using llama.cpp server on port {llama_port}, model: {model_id}")
            return f"llamacpp:{model_id}", base_url
    except Exception:
        pass

    # 5. Paid APIs — only if explicitly configured
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude:claude-haiku-4-5-20251001", None
    if os.environ.get("OPENAI_API_KEY"):
        return "openai:gpt-4o-mini", None

    raise RuntimeError(
        "No LLM backend found. Start one of:\n"
        "  msty.ai       — open the app (runs on localhost:10000, free)\n"
        "  Ollama        — 'ollama serve' (runs on localhost:11434, free)\n"
        "  llama.cpp     — 'llama-server -m model.gguf' (runs on localhost:8080, free)\n"
        "  Or set ATLAS_LLM_MODEL (e.g. 'claude:haiku', 'openai:gpt-4o-mini', 'llamacpp:model')\n"
        "  See docs/CONFIGURATION.md for full setup instructions."
    )


def extract_facts(
    processed_text: str,
    source_id: str,
    config: AtlasConfig,
    model: str | None = None,
) -> list[FactCandidate]:
    """
    Send processed text to LLM with extraction prompt.
    Auto-detects available LLM if model not specified.
    Supported model prefixes: 'ollama:', 'claude:', 'openai:'
    """
    base_url = None
    if model is None:
        model, base_url = _detect_model()

    prompt = EXTRACTION_PROMPT.format(
        source_id=source_id,
        processed_text=processed_text[:8000],
    )

    try:
        raw_response = _call_llm(prompt, model, base_url=base_url)
        facts_data = _parse_response(raw_response)
    except Exception as e:
        logger.warning(f"Fact extraction failed for {source_id}: {e}")
        return []

    candidates = []
    now = datetime.now(timezone.utc).isoformat()

    GARBAGE_VALUES = {"none", "null", "n/a", "unknown", "undefined", "na", "tbd", ""}

    for item in facts_data:
        if not all(k in item for k in ("subject", "predicate", "object")):
            continue

        # Validate values are real strings, not null/empty/garbage
        subj = item["subject"]
        pred = item["predicate"]
        obj = item["object"]
        if not all(
            isinstance(v, str) and v.strip() and v.strip().lower() not in GARBAGE_VALUES
            for v in (subj, pred, obj)
        ):
            continue

        candidate = FactCandidate(
            candidate_id=generate_id("cand"),
            source_id=source_id,
            subject=subj.strip(),
            predicate=pred.strip(),
            object=obj.strip(),
            valid_from=item.get("valid_from"),
            valid_to=item.get("valid_to"),
            extraction_model=model,
            extracted_at=now,
        )
        candidates.append(candidate)

    # Save to database
    conn = get_connection(config.db_path)
    for c in candidates:
        conn.execute(
            """INSERT INTO fact_candidates
               (candidate_id, source_id, subject, predicate, object,
                valid_from, valid_to, extraction_model, extracted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (c.candidate_id, c.source_id, c.subject, c.predicate, c.object,
             c.valid_from, c.valid_to, c.extraction_model, c.extracted_at),
        )
    conn.commit()

    return candidates


def _call_llm(prompt: str, model: str, base_url: str | None = None) -> str:
    """Call the appropriate LLM backend."""
    prefix, _, model_name = model.partition(":")

    if prefix == "ollama":
        return _call_ollama(prompt, model_name)
    elif prefix == "claude":
        return _call_claude(prompt, model_name)
    elif prefix == "openai":
        return _call_openai(prompt, model_name, base_url=base_url)
    elif prefix == "llamacpp":
        return _call_llamacpp(prompt, model_name, base_url=base_url)
    else:
        raise ValueError(f"Unknown model prefix: {prefix}. Use 'ollama:', 'claude:', 'openai:', or 'llamacpp:'")


def _llm_timeout_seconds() -> float:
    """Read the request timeout for external LLM calls."""
    raw = os.environ.get("ATLAS_LLM_TIMEOUT_SECONDS", str(DEFAULT_LLM_TIMEOUT_SECONDS))
    try:
        timeout = float(raw)
    except ValueError:
        timeout = DEFAULT_LLM_TIMEOUT_SECONDS
    return max(timeout, 1.0)


def _call_ollama(prompt: str, model_name: str) -> str:
    """Call Ollama local LLM."""
    import httpx

    response = httpx.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        },
        timeout=_llm_timeout_seconds(),
    )
    response.raise_for_status()
    return response.json().get("response", "")


def _call_claude(prompt: str, model_name: str) -> str:
    """Call Claude API."""
    import httpx
    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model_name or "claude-sonnet-4-20250514",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=_llm_timeout_seconds(),
    )
    response.raise_for_status()
    content = response.json()["content"]
    return content[0]["text"] if content else ""


def _call_openai(prompt: str, model_name: str, base_url: str | None = None) -> str:
    """Call OpenAI-compatible API (also works with msty.ai, LM Studio, etc.)."""
    import httpx
    import os

    api_key = os.environ.get("OPENAI_API_KEY", "not-needed")
    url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    response = httpx.post(
        f"{url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model_name or "gpt-4",
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=_llm_timeout_seconds(),
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _call_llamacpp(prompt: str, model_name: str, base_url: str | None = None) -> str:
    """Call llama.cpp server (OpenAI-compatible /v1/chat/completions endpoint)."""
    import httpx
    import os

    port = int(os.environ.get("LLAMA_CPP_PORT", "8080"))
    url = base_url or f"http://localhost:{port}/v1"

    response = httpx.post(
        f"{url}/chat/completions",
        headers={"Content-Type": "application/json"},
        json={
            "model": model_name or "default",
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=_llm_timeout_seconds(),
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _parse_response(raw: str) -> list[dict]:
    """Parse LLM response into list of fact dicts."""
    # Try to extract JSON array from response
    raw = raw.strip()

    # Try direct parse
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "facts" in data:
            return data["facts"]
        return [data] if isinstance(data, dict) else []
    except json.JSONDecodeError:
        pass

    # Try to find JSON array in response
    import re
    match = re.search(r'\[[\s\S]*\]', raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return []
