"""Schedule primitives — maps interval strings to seconds and computes which
agents are due to run.
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.agents.state import load_state


# Human strings → seconds. "manual" and "off" are never auto-scheduled.
INTERVAL_SECONDS: dict[str, Optional[int]] = {
    "off": None,
    "manual": None,
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
}

VALID_INTERVALS = tuple(INTERVAL_SECONDS.keys())


def parse_interval_seconds(interval: str) -> Optional[int]:
    """Return the period in seconds, or None for off/manual/unknown."""
    return INTERVAL_SECONDS.get((interval or "").strip().lower())


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def agent_is_due(
    schedule: str,
    last_run_at: Optional[str],
    now: Optional[datetime] = None,
) -> bool:
    """True if the agent should run right now per its schedule."""
    period = parse_interval_seconds(schedule)
    if period is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    last = _parse_iso(last_run_at)
    if last is None:
        return True
    # Normalise tz so a naive vs aware mismatch doesn't throw.
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - last).total_seconds() >= period


def agents_due(repo_root: Path, now: Optional[datetime] = None) -> list[str]:
    """Return the names of agents whose schedule is due to fire."""
    from src.agents.registry import list_agents  # avoid cycle
    due: list[str] = []
    for meta in list_agents(repo_root):
        if meta.state.get("last_status") == "running":
            continue
        if agent_is_due(meta.config.get("schedule", "manual"),
                        meta.state.get("last_run_at"), now=now):
            due.append(meta.name)
    return due
