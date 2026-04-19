"""Agent registry — discovers agents from the filesystem.

An agent is any subfolder of `agents/` that contains a `config.yaml`. The
matching run function must be registered in `AGENT_RUN_FNS` below (keyed by
the agent folder name). Agents without a registered run fn still show up in
the UI but cannot be triggered — they're flagged as "not wired up".
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

from src.agents.state import load_state


# ---------------------------------------------------------------------------
# Run-function registry
# ---------------------------------------------------------------------------

# Filled in lazily at import time to avoid circular imports with deep_search.py.
AGENT_RUN_FNS: dict[str, Callable] = {}


def _register_builtin_agents() -> None:
    import logging
    log = logging.getLogger(__name__)
    # Imports are deferred so the agents module is usable in tests even when
    # the LLM libraries aren't importable.
    try:
        from src.agents.deep_search import run_deep_search
        AGENT_RUN_FNS["deepSearch"] = run_deep_search
    except Exception as exc:
        log.warning("failed to register deepSearch agent: %s", exc)

    try:
        from src.agents.digest_agent import run_digest_agent
        AGENT_RUN_FNS["digestAgent"] = run_digest_agent
    except Exception as exc:
        log.warning("failed to register digestAgent: %s", exc)

    try:
        from src.agents.lint_agent import run_lint_agent
        AGENT_RUN_FNS["lintAgent"] = run_lint_agent
    except Exception as exc:
        log.warning("failed to register lintAgent: %s", exc)

    try:
        from src.agents.source_discovery import run_source_discovery
        AGENT_RUN_FNS["sourceDiscovery"] = run_source_discovery
    except Exception as exc:
        log.warning("failed to register sourceDiscovery: %s", exc)

    try:
        from src.agents.conflic_agent import run_conflic_agent
        AGENT_RUN_FNS["conflicAgent"] = run_conflic_agent
    except Exception as exc:
        log.warning("failed to register conflicAgent: %s", exc)


_register_builtin_agents()


# ---------------------------------------------------------------------------
# Disk-backed agent metadata
# ---------------------------------------------------------------------------

AGENTS_DIR_NAME = "agents"


@dataclass
class AgentMeta:
    name: str
    folder: Path
    config: dict = field(default_factory=dict)
    prompt: str = ""
    state: dict = field(default_factory=dict)
    config_exists: bool = True
    prompt_exists: bool = True

    @property
    def has_run_fn(self) -> bool:
        return self.name in AGENT_RUN_FNS

    @property
    def description(self) -> str:
        return str(self.config.get("description") or "").strip()

    @property
    def schedule(self) -> str:
        return str(self.config.get("schedule", "manual")).strip().lower()


def agents_root(repo_root: Path) -> Path:
    return repo_root / AGENTS_DIR_NAME


def config_path(agent_name: str, repo_root: Path) -> Path:
    return agents_root(repo_root) / agent_name / "config.yaml"


def prompt_path(agent_name: str, repo_root: Path) -> Path:
    return agents_root(repo_root) / agent_name / "prompt.md"


def _read_config(path: Path) -> tuple[dict, bool]:
    if not path.exists():
        return {}, False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}, True
    if not isinstance(data, dict):
        return {}, True
    return data, True


def _read_prompt(path: Path) -> tuple[str, bool]:
    if not path.exists():
        return "", False
    return path.read_text(encoding="utf-8"), True


def load_agent(agent_name: str, repo_root: Path) -> Optional[AgentMeta]:
    folder = agents_root(repo_root) / agent_name
    if not folder.is_dir():
        return None
    cfg, cfg_exists = _read_config(config_path(agent_name, repo_root))
    prompt, prompt_exists = _read_prompt(prompt_path(agent_name, repo_root))
    state = load_state(agent_name, repo_root)
    return AgentMeta(
        name=agent_name,
        folder=folder,
        config=cfg,
        prompt=prompt,
        state=state,
        config_exists=cfg_exists,
        prompt_exists=prompt_exists,
    )


def list_agents(repo_root: Path) -> list[AgentMeta]:
    base = agents_root(repo_root)
    if not base.exists():
        return []
    out: list[AgentMeta] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        meta = load_agent(child.name, repo_root)
        if meta is not None:
            out.append(meta)
    return out
