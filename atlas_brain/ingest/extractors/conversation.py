"""Chat export parsing — Claude, ChatGPT, Slack JSON."""

import json
import re
from pathlib import Path

from atlas_brain.models import ProcessedDocument


def _parse_json_chat(data: dict | list) -> list[dict]:
    """Parse various JSON chat export formats."""
    messages = []

    # ChatGPT format: {"mapping": {...}} or list of messages
    if isinstance(data, dict):
        if "mapping" in data:
            # ChatGPT export
            for node in data["mapping"].values():
                msg = node.get("message")
                if msg and msg.get("content") and msg["content"].get("parts"):
                    role = msg.get("author", {}).get("role", "unknown")
                    text = "\n".join(str(p) for p in msg["content"]["parts"] if isinstance(p, str))
                    if text.strip():
                        messages.append({"speaker": role, "text": text})
        elif "messages" in data:
            # Generic messages array format
            for msg in data["messages"]:
                speaker = msg.get("role") or msg.get("author") or msg.get("from") or "unknown"
                text = msg.get("content") or msg.get("text") or msg.get("message") or ""
                if isinstance(text, list):
                    text = "\n".join(str(p) for p in text)
                if text.strip():
                    messages.append({"speaker": speaker, "text": text})
    elif isinstance(data, list):
        # Slack export or list of messages
        for msg in data:
            if isinstance(msg, dict):
                speaker = msg.get("user") or msg.get("username") or msg.get("role") or "unknown"
                text = msg.get("text") or msg.get("content") or ""
                if text.strip():
                    messages.append({"speaker": speaker, "text": text})

    return messages


def _parse_text_chat(text: str) -> list[dict]:
    """Parse plain text conversation with speaker labels."""
    messages = []
    current_speaker = None
    current_text = []

    for line in text.splitlines():
        # Match speaker patterns like "Human:", "Assistant:", "User:", etc.
        speaker_match = re.match(
            r'^(Human|Assistant|User|AI|System|Speaker\s*\d*|[A-Z][a-z]+)\s*:\s*(.*)',
            line,
        )
        if speaker_match:
            if current_speaker and current_text:
                messages.append({
                    "speaker": current_speaker,
                    "text": "\n".join(current_text).strip(),
                })
            current_speaker = speaker_match.group(1)
            current_text = [speaker_match.group(2)] if speaker_match.group(2) else []
        else:
            current_text.append(line)

    if current_speaker and current_text:
        messages.append({
            "speaker": current_speaker,
            "text": "\n".join(current_text).strip(),
        })

    return messages


def extract(file_path: Path) -> ProcessedDocument:
    """Extract from conversation exports."""
    raw = file_path.read_text(errors="replace")
    messages = []

    # Try JSON first
    if file_path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
            messages = _parse_json_chat(data)
        except json.JSONDecodeError:
            pass

    # Fall back to text parsing
    if not messages:
        messages = _parse_text_chat(raw)

    # Build readable output
    parts = []
    speakers = set()
    for msg in messages:
        speakers.add(msg["speaker"])
        parts.append(f"**{msg['speaker']}:** {msg['text']}")

    full_text = "\n\n".join(parts) if parts else raw
    title = file_path.stem

    return ProcessedDocument(
        text=full_text,
        title=title,
        author=None,
        created_date=None,
        word_count=len(full_text.split()),
        sections=[],
        metadata={
            "speakers": list(speakers),
            "message_count": len(messages),
        },
    )
