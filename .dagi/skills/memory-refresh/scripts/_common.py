"""Shared utilities for memory-refresh lint scripts."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

WIKI_ROOT = Path(r"G:\My Drive\black_grimoire\dagi-memory\wiki")

# Category detection from path
CATEGORY_MAP = {
    "projects": "projects",
    "todos": "todos",
    "knowledge": "knowledge",
    "events": "events",
}

# Required fields per category
SHARED_FIELDS = {"title", "description", "tags", "date_created", "links"}
CATEGORY_FIELDS = {
    "projects": {"status", "objective"},  # overview.md only
    "todos": {"status", "deadline", "frequency"},
    "knowledge": set(),
    "events": {"date"},
}

# Valid values for enum fields
VALID_STATUS_PROJECT = {"active", "completed", "archived", "paused"}
VALID_STATUS_TODO = {"pending", "in-progress", "completed", "dropped"}
VALID_FREQUENCY = {"one-off", "daily", "weekly", "monthly"}


def detect_category(path: Path) -> str | None:
    """Detect category from file path relative to wiki root."""
    try:
        rel = path.relative_to(WIKI_ROOT)
    except ValueError:
        return None
    parts = rel.parts
    if parts and parts[0] in CATEGORY_MAP:
        return CATEGORY_MAP[parts[0]]
    return None


def is_index_file(path: Path) -> bool:
    return path.name == ".index.md"


def is_overview_file(path: Path) -> bool:
    return path.name == "overview.md"


def parse_frontmatter(path: Path) -> dict | None:
    """Parse YAML frontmatter from a markdown file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end == -1:
        return None
    import yaml
    try:
        return yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None


def extract_wikilinks(path: Path) -> list[str]:
    """Extract all [[wikilinks]] from a file's content."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return re.findall(r"\[\[(.+?)\]\]", text)


def all_content_files(
    scope: str | None = None,
) -> list[Path]:
    """List all .md content files (excluding .index.md)."""
    root = WIKI_ROOT
    if scope:
        root = WIKI_ROOT / scope
    if not root.exists():
        return []
    return [
        p for p in root.rglob("*.md")
        if not is_index_file(p) and p.name != "log.md"
    ]


def emit_issues(issues: list[dict]) -> None:
    """Print issues as JSON to stdout."""
    json.dump(issues, sys.stdout, indent=2)
    sys.stdout.write("\n")
