"""Paths, settings, and ATLAS.md parsing."""

from pathlib import Path
from dataclasses import dataclass, field


def find_atlas_root() -> Path:
    """Find the Atlas Brain root directory by looking for ATLAS.md upward from cwd."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "ATLAS.md").exists():
            return parent
    return cwd


@dataclass
class AtlasConfig:
    """Atlas Brain configuration."""

    root: Path = field(default_factory=find_atlas_root)

    @property
    def inbox_dir(self) -> Path:
        return self.root / "inbox"

    @property
    def sources_dir(self) -> Path:
        return self.root / "sources"

    @property
    def processed_dir(self) -> Path:
        return self.root / "processed"

    @property
    def wiki_dir(self) -> Path:
        return self.root / "wiki"

    @property
    def outputs_dir(self) -> Path:
        return self.root / "outputs"

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def db_path(self) -> Path:
        return self.state_dir / "atlas.db"

    @property
    def chroma_dir(self) -> Path:
        return self.state_dir / "chroma"

    @property
    def atlas_md_path(self) -> Path:
        return self.root / "ATLAS.md"

    SOURCE_SUBTYPES = [
        "articles", "conversations", "documents", "code", "meetings", "media", "exports"
    ]

    def all_dirs(self) -> list[Path]:
        """All directories that should exist."""
        dirs = [
            self.inbox_dir,
            self.processed_dir,
            self.wiki_dir,
            self.outputs_dir,
            self.agents_dir,
            self.state_dir,
            self.logs_dir,
        ]
        for subtype in self.SOURCE_SUBTYPES:
            dirs.append(self.sources_dir / subtype)
        return dirs


def parse_atlas_md(path: Path) -> dict:
    """Parse ATLAS.md for identity fields."""
    result = {"owner": "", "purpose": "", "projects": [], "people": []}
    if not path.exists():
        return result

    text = path.read_text()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Owner:"):
            result["owner"] = line.split(":", 1)[1].strip()
        elif line.startswith("Purpose:"):
            result["purpose"] = line.split(":", 1)[1].strip()
        elif line.startswith("Active projects:"):
            result["projects"] = [
                p.strip() for p in line.split(":", 1)[1].split(",") if p.strip()
            ]
        elif line.startswith("Key people:"):
            result["people"] = [
                p.strip() for p in line.split(":", 1)[1].split(",") if p.strip()
            ]
    return result
