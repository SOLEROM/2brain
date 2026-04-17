"""Agents subsystem — post-analysis workers whose config + prompt live on disk.

Each agent is a subfolder of `agents/<name>/` containing:
  - config.yaml   — schedule + agent-specific parameters (user-editable)
  - prompt.md     — LLM prompt template (user-editable)
  - state.yaml    — runtime state (written by the runner)
  - runs/         — optional: recent run records

The registry maps an agent name to a Python callable that actually does the
work. UI surfaces (list + detail) and the background scheduler are all
driven by on-disk config.
"""
from src.agents.registry import AGENT_RUN_FNS, list_agents, load_agent
from src.agents.runner import run_agent
from src.agents.state import load_state, save_state
from src.agents.schedule import agents_due, parse_interval_seconds

__all__ = [
    "AGENT_RUN_FNS",
    "list_agents",
    "load_agent",
    "run_agent",
    "load_state",
    "save_state",
    "agents_due",
    "parse_interval_seconds",
]
