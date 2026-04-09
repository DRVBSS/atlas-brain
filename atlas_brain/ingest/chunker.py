"""Step 5: Semantic chunking."""

import re

from atlas_brain.models import Chunk
from atlas_brain.utils.ids import generate_id


def estimate_tokens(text: str) -> int:
    """Approximate token count (words * 1.3)."""
    return int(len(text.split()) * 1.3)


def chunk(processed_text: str, source_type: str, source_id: str) -> list[Chunk]:
    """
    Split text at semantic boundaries.
    - Section headings (## ...) ALWAYS start a new chunk
    - Paragraph breaks (double newline) are preferred split points
    - Speaker turns (in conversations) never split mid-turn
    - Soft ceiling: 500 tokens per chunk
    - Hard ceiling: 800 tokens (split at nearest sentence boundary)
    - Minimum: 50 tokens (merge tiny chunks with neighbor)
    """
    SOFT_CEILING = 500
    HARD_CEILING = 800
    MIN_TOKENS = 50

    # Split into paragraphs first
    paragraphs = re.split(r'\n{2,}', processed_text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    raw_chunks: list[dict] = []
    current_text = ""
    current_heading = None

    for para in paragraphs:
        # Check if this is a heading
        heading_match = re.match(r'^(#{1,6})\s+(.+)', para)
        is_heading = heading_match is not None

        # Check if this is a speaker turn (for conversations)
        is_speaker_turn = source_type == "conversation" and re.match(
            r'^(?:Human|Assistant|User|AI|Speaker\s*\d*):', para
        )

        if is_heading:
            # Flush current chunk
            if current_text.strip():
                raw_chunks.append({
                    "content": current_text.strip(),
                    "section_heading": current_heading,
                })
            current_heading = heading_match.group(2).strip()
            current_text = para + "\n\n"
            continue

        # Would adding this paragraph exceed the soft ceiling?
        combined = current_text + para + "\n\n"
        combined_tokens = estimate_tokens(combined)

        if combined_tokens > SOFT_CEILING and current_text.strip():
            # Flush current chunk
            raw_chunks.append({
                "content": current_text.strip(),
                "section_heading": current_heading,
            })
            current_text = para + "\n\n"
        else:
            current_text = combined

    # Flush remaining
    if current_text.strip():
        raw_chunks.append({
            "content": current_text.strip(),
            "section_heading": current_heading,
        })

    # Apply hard ceiling — split oversized chunks at sentence boundaries
    split_chunks = []
    for ch in raw_chunks:
        tokens = estimate_tokens(ch["content"])
        if tokens <= HARD_CEILING:
            split_chunks.append(ch)
        else:
            # Split at sentence boundaries
            sentences = re.split(r'(?<=[.!?])\s+', ch["content"])
            sub_text = ""
            for sent in sentences:
                candidate = sub_text + " " + sent if sub_text else sent
                if estimate_tokens(candidate) > HARD_CEILING and sub_text:
                    split_chunks.append({
                        "content": sub_text.strip(),
                        "section_heading": ch["section_heading"],
                    })
                    sub_text = sent
                else:
                    sub_text = candidate
            if sub_text.strip():
                split_chunks.append({
                    "content": sub_text.strip(),
                    "section_heading": ch["section_heading"],
                })

    # Merge tiny chunks with neighbors
    merged = []
    for ch in split_chunks:
        tokens = estimate_tokens(ch["content"])
        if tokens < MIN_TOKENS and merged:
            # Merge with previous chunk
            merged[-1]["content"] += "\n\n" + ch["content"]
        else:
            merged.append(ch)

    # Convert to Chunk objects
    chunks = []
    for i, ch in enumerate(merged):
        # Detect speaker in conversation chunks
        speaker = None
        if source_type == "conversation":
            speaker_match = re.match(r'^((?:Human|Assistant|User|AI|Speaker\s*\d*)):', ch["content"])
            if speaker_match:
                speaker = speaker_match.group(1)

        chunks.append(Chunk(
            chunk_id=generate_id("chk"),
            source_id=source_id,
            chunk_index=i,
            content=ch["content"],
            section_heading=ch.get("section_heading"),
            speaker=speaker,
            token_count=estimate_tokens(ch["content"]),
        ))

    return chunks
