"""Media extraction — images (OCR placeholder) and audio/video (transcription stub)."""

import logging
from pathlib import Path

from atlas_brain.models import ProcessedDocument

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}
SUPPORTED_AUDIO_VIDEO = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4", ".mov", ".avi", ".mkv", ".webm"}


def extract(file_path: Path) -> ProcessedDocument:
    """Extract content from media files."""
    suffix = file_path.suffix.lower()

    if suffix in SUPPORTED_IMAGE:
        return _extract_image(file_path)
    elif suffix in SUPPORTED_AUDIO_VIDEO:
        return _extract_audio_video(file_path)
    else:
        raise ValueError(f"Unsupported media format: {suffix}")


def _extract_image(file_path: Path) -> ProcessedDocument:
    """Image text extraction (OCR placeholder)."""
    return ProcessedDocument(
        text=f"[Image: {file_path.name}. OCR not yet implemented.]",
        title=file_path.stem,
        metadata={"media_type": "image", "format": file_path.suffix},
    )


def _extract_audio_video(file_path: Path) -> ProcessedDocument:
    """
    Audio/video extraction stub.

    Override this with your own transcription pipeline by setting
    ATLAS_TRANSCRIPTION_BACKEND in your environment or configuring
    a transcription service in ATLAS.md.
    """
    logger.warning(f"No transcription backend configured for {file_path.name}")
    return ProcessedDocument(
        text=f"[Recording: {file_path.name}. No transcription backend configured.]",
        title=file_path.stem,
        metadata={"media_type": "audio_video", "format": file_path.suffix},
    )
