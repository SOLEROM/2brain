"""Background task that wakes periodically and runs due agents.

Runs in a single asyncio task on the FastAPI event loop. Each scheduler tick:
  1. Enumerate registered agents via `list_agents(repo_root)`.
  2. For each agent whose schedule is due, offload `run_agent(...)` to a
     worker thread so it cannot block the event loop.
  3. Sleep `tick_seconds` and repeat.

A single tick runs at most one agent so a slow agent doesn't stall its
siblings for a whole loop iteration. Agents not executed this tick are
picked up the next one.
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from src.agents.runner import run_agent
from src.agents.schedule import agents_due

log = logging.getLogger(__name__)


async def scheduler_loop(
    repo_root: Path,
    tick_seconds: int = 60,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Run forever (or until `stop_event` is set)."""
    while True:
        if stop_event is not None and stop_event.is_set():
            return
        try:
            due = agents_due(repo_root)
            if due:
                name = due[0]
                log.info("scheduler: running agent %s", name)
                await asyncio.to_thread(run_agent, name, repo_root)
        except Exception as exc:
            log.exception("scheduler tick failed: %s", exc)
        try:
            await asyncio.sleep(tick_seconds)
        except asyncio.CancelledError:
            return
