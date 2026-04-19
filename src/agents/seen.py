"""Per-agent ledger of item IDs already processed.

Each agent that honours `work_scope` persists the set of IDs it processed
to `agents/<name>/seen.json`. On the next run the runner loads the set and
passes it to the agent so `work_scope=new` can skip already-processed items.

An "item ID" is agent-defined. For page-oriented agents the recommended
shape is `<path>@<updated_at>` so an updated page becomes a new item.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from src.utils import atomic_write


VALID_SCOPES = ("all", "new")


def seen_path(agent_name: str, repo_root: Path) -> Path:
    return repo_root / "agents" / agent_name / "seen.json"


def load_seen(agent_name: str, repo_root: Path) -> set[str]:
    path = seen_path(agent_name, repo_root)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(x) for x in data if isinstance(x, (str, int, float))}


def save_seen(agent_name: str, repo_root: Path, seen: Iterable[str]) -> None:
    items = sorted({str(x) for x in seen})
    atomic_write(
        seen_path(agent_name, repo_root),
        json.dumps(items, indent=2, ensure_ascii=False) + "\n",
    )


def clear_seen(agent_name: str, repo_root: Path) -> None:
    path = seen_path(agent_name, repo_root)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


@dataclass
class SeenTracker:
    """Mutable helper handed to an agent's run fn.

    The agent reads `initial` (the set as-of this run's start) to decide
    which items are new, then calls `mark(...)` to record items it
    processed. The runner persists `marked` on successful completion.
    """
    initial: set[str] = field(default_factory=set)
    marked: set[str] = field(default_factory=set)

    def mark(self, *ids: str) -> None:
        for i in ids:
            if i:
                self.marked.add(str(i))

    def mark_many(self, ids: Iterable[str]) -> None:
        for i in ids:
            if i:
                self.marked.add(str(i))

    def is_new(self, item_id: str) -> bool:
        return item_id not in self.initial

    def filter_new(self, items: Iterable, key) -> list:
        """Return only items whose `key(item)` is not in `initial`."""
        return [it for it in items if key(it) not in self.initial]

    @property
    def final(self) -> set[str]:
        """The set to persist after a successful run — prior + this run."""
        return self.initial | self.marked


def normalize_scope(value) -> str:
    v = str(value or "").strip().lower()
    return v if v in VALID_SCOPES else "all"
