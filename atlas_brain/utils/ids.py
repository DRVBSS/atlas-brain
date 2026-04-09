"""UUID generation with prefixes for Atlas Brain entities."""

import uuid


def generate_id(prefix: str) -> str:
    """Generate a prefixed ID like 'src_a7f3b2e1'."""
    short = uuid.uuid4().hex[:8]
    return f"{prefix}_{short}"
