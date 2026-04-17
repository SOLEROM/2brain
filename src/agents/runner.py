"""Synchronously execute an agent's run function and persist its state."""
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from src.agents.registry import AGENT_RUN_FNS, load_agent
from src.agents.state import save_state, update_state
from src.utils import append_line, atomic_write, hash8, now_iso


@dataclass
class AgentRun:
    agent: str
    status: str          # "ok" | "failed"
    job_id: str
    started_at: str
    completed_at: str
    duration_s: float
    message: str
    outputs: list[str] = field(default_factory=list)
    error: Optional[str] = None


def _build_job_id(agent_name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"job_{ts}_agent-{agent_name}_{hash8(agent_name + ts)}"


def _write_job_yaml(repo_root: Path, bucket: str, job: dict) -> None:
    dst_dir = repo_root / "jobs" / bucket
    dst_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(
        dst_dir / f"{job['job_id']}.yaml",
        yaml.dump(job, allow_unicode=True, sort_keys=False),
    )


def run_agent(
    agent_name: str,
    repo_root: Path,
    *,
    question_override: Optional[str] = None,
) -> AgentRun:
    """Run an agent end-to-end. Persists state + job record. Never raises."""
    meta = load_agent(agent_name, repo_root)
    started = datetime.now(timezone.utc)
    started_iso = started.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    job_id = _build_job_id(agent_name)

    if meta is None:
        completed_iso = now_iso()
        err = f"Agent '{agent_name}' not found on disk."
        _write_job_yaml(repo_root, "failed", {
            "job_id": job_id, "job_type": "agent-run", "domain": None,
            "status": "failed", "created_at": started_iso,
            "started_at": started_iso, "completed_at": completed_iso,
            "input": agent_name, "outputs": [],
            "agent": agent_name, "error": err,
        })
        return AgentRun(
            agent=agent_name, status="failed", job_id=job_id,
            started_at=started_iso, completed_at=completed_iso,
            duration_s=0.0, message=err, error=err,
        )

    run_fn = AGENT_RUN_FNS.get(agent_name)
    if run_fn is None:
        completed_iso = now_iso()
        err = f"Agent '{agent_name}' has no run function registered in AGENT_RUN_FNS."
        _write_job_yaml(repo_root, "failed", {
            "job_id": job_id, "job_type": "agent-run",
            "domain": meta.config.get("domain"),
            "status": "failed", "created_at": started_iso,
            "started_at": started_iso, "completed_at": completed_iso,
            "input": agent_name, "outputs": [],
            "agent": agent_name, "error": err,
        })
        update_state(
            agent_name, repo_root,
            last_run_at=started_iso, last_status="failed",
            last_duration_s=0.0, last_message=err, last_job_id=job_id,
            last_outputs=[], last_error=err,
        )
        return AgentRun(
            agent=agent_name, status="failed", job_id=job_id,
            started_at=started_iso, completed_at=completed_iso,
            duration_s=0.0, message=err, error=err,
        )

    # Flip state to running so the UI + scheduler don't double-fire.
    update_state(
        agent_name, repo_root,
        last_status="running", last_job_id=job_id,
    )

    t0 = time.monotonic()
    try:
        result: dict = run_fn(
            meta=meta,
            repo_root=repo_root,
            job_id=job_id,
            question_override=question_override,
        ) or {}
        duration = time.monotonic() - t0
        completed_iso = now_iso()
        outputs = list(result.get("outputs") or [])
        message = str(result.get("message") or "ok")
        _write_job_yaml(repo_root, "completed", {
            "job_id": job_id, "job_type": "agent-run",
            "domain": meta.config.get("domain"),
            "status": "completed", "created_at": started_iso,
            "started_at": started_iso, "completed_at": completed_iso,
            "heartbeat_at": completed_iso,
            "input": agent_name, "outputs": outputs,
            "agent": agent_name,
        })
        update_state(
            agent_name, repo_root,
            last_run_at=started_iso, last_status="ok",
            last_duration_s=round(duration, 2), last_message=message,
            last_job_id=job_id, last_outputs=outputs, last_error=None,
        )
        try:
            append_line(
                repo_root / "audit" / "agent-actions.log",
                f"{completed_iso} agent-run | {agent_name} | ok | "
                f"duration={duration:.1f}s | outputs={len(outputs)}",
            )
        except Exception:
            pass
        return AgentRun(
            agent=agent_name, status="ok", job_id=job_id,
            started_at=started_iso, completed_at=completed_iso,
            duration_s=duration, message=message, outputs=outputs,
        )
    except Exception as exc:
        duration = time.monotonic() - t0
        completed_iso = now_iso()
        err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"
        _write_job_yaml(repo_root, "failed", {
            "job_id": job_id, "job_type": "agent-run",
            "domain": meta.config.get("domain"),
            "status": "failed", "created_at": started_iso,
            "started_at": started_iso, "completed_at": completed_iso,
            "input": agent_name, "outputs": [],
            "agent": agent_name, "error": err,
        })
        update_state(
            agent_name, repo_root,
            last_run_at=started_iso, last_status="failed",
            last_duration_s=round(duration, 2),
            last_message=f"{type(exc).__name__}: {exc}",
            last_job_id=job_id, last_outputs=[], last_error=err,
        )
        try:
            append_line(
                repo_root / "audit" / "agent-actions.log",
                f"{completed_iso} agent-run | {agent_name} | failed | "
                f"duration={duration:.1f}s | error={type(exc).__name__}: {exc}",
            )
        except Exception:
            pass
        return AgentRun(
            agent=agent_name, status="failed", job_id=job_id,
            started_at=started_iso, completed_at=completed_iso,
            duration_s=duration, message=f"{type(exc).__name__}: {exc}",
            error=err,
        )
