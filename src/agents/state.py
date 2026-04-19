"""Read/write per-agent state.yaml atomically."""
from pathlib import Path
from typing import Optional

import yaml

from src.utils import atomic_write, coerce_datetimes


def state_path(agent_name: str, repo_root: Path) -> Path:
    return repo_root / "agents" / agent_name / "state.yaml"


def load_state(agent_name: str, repo_root: Path) -> dict:
    """Return the current state dict, or an empty shell when no file exists."""
    path = state_path(agent_name, repo_root)
    default = {
        "last_run_at": None,
        "last_status": None,        # "ok" | "failed" | "running"
        "last_duration_s": None,
        "last_message": None,
        "last_job_id": None,
        "last_outputs": [],
        "last_error": None,
    }
    if not path.exists():
        return default
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return default
    if not isinstance(data, dict):
        return default
    default.update(coerce_datetimes(data))
    return default


def save_state(agent_name: str, repo_root: Path, state: dict) -> None:
    """Persist state.yaml atomically (survives concurrent reads)."""
    path = state_path(agent_name, repo_root)
    # Keep scalar None for missing fields — yaml.dump renders them as `null`
    # which reads back cleanly.
    atomic_write(path, yaml.dump(state, sort_keys=False, allow_unicode=True))


def update_state(agent_name: str, repo_root: Path, **fields) -> dict:
    """Merge `fields` into the existing state and persist. Returns the new state."""
    current = load_state(agent_name, repo_root)
    current.update(fields)
    save_state(agent_name, repo_root, current)
    return current
