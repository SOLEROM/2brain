"""Agents tab — list registered agents, view/edit their on-disk config &
prompt, trigger manual runs, set a periodic schedule.
"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.agents.registry import (
    AgentMeta,
    config_path,
    list_agents,
    load_agent,
    prompt_path,
)
from src.agents.runner import run_agent
from src.agents.schedule import VALID_INTERVALS, parse_interval_seconds
from src.utils import atomic_write

router = APIRouter()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@router.get("/agents", response_class=HTMLResponse)
async def agents_list(request: Request):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    agents = [_to_list_dict(m) for m in list_agents(repo_root)]
    return templates.TemplateResponse(request, "agents.html", {
        "agents": agents,
        "intervals": VALID_INTERVALS,
    })


@router.get("/agents/{name}", response_class=HTMLResponse)
async def agent_detail(request: Request, name: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates

    meta = load_agent(name, repo_root)
    if meta is None:
        return _not_found(request, name)

    return templates.TemplateResponse(request, "agent_detail.html", {
        "agent": _to_detail_dict(meta, repo_root),
        "intervals": VALID_INTERVALS,
    })


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@router.post("/agents/{name}/run")
async def agents_run(
    request: Request,
    name: str,
    question: str = Form(default=""),
):
    repo_root: Path = request.app.state.repo_root
    meta = load_agent(name, repo_root)
    if meta is None:
        return _not_found(request, name)

    question_override = question.strip() or None

    # Fire-and-forget: run in a worker thread so the HTTP request returns fast
    # and the UI can poll /agents/<name> for state updates.
    def _runner():
        run_agent(name, repo_root, question_override=question_override)

    asyncio.get_event_loop().run_in_executor(None, _runner)
    return RedirectResponse(f"/agents/{name}", status_code=303)


@router.post("/agents/{name}/schedule")
async def agents_set_schedule(
    request: Request,
    name: str,
    schedule: str = Form(...),
):
    repo_root: Path = request.app.state.repo_root
    meta = load_agent(name, repo_root)
    if meta is None:
        return _not_found(request, name)

    schedule_norm = (schedule or "").strip().lower()
    if schedule_norm not in VALID_INTERVALS:
        schedule_norm = "manual"

    cfg = dict(meta.config)
    cfg["schedule"] = schedule_norm
    atomic_write(
        config_path(name, repo_root),
        yaml.dump(cfg, sort_keys=False, allow_unicode=True),
    )
    return RedirectResponse(f"/agents/{name}", status_code=303)


@router.post("/agents/{name}/config")
async def agents_save_config(request: Request, name: str):
    """Save the full config.yaml from the detail-page form.

    Known typed fields are parsed with best-effort coercion; unknown keys are
    preserved from the existing config so manual edits survive.
    """
    repo_root: Path = request.app.state.repo_root
    meta = load_agent(name, repo_root)
    if meta is None:
        return _not_found(request, name)

    form = await request.form()
    new_cfg = dict(meta.config)  # start from current, round-trip unknown keys

    for key in ["description", "domain", "question", "model", "name"]:
        if key in form:
            new_cfg[key] = str(form[key]).strip()

    for key in ["max_tokens", "max_pages", "max_context_chars"]:
        if key in form:
            raw = str(form[key]).strip()
            if raw:
                try:
                    new_cfg[key] = int(raw)
                except ValueError:
                    pass

    if "schedule" in form:
        sched = str(form["schedule"]).strip().lower()
        if sched in VALID_INTERVALS:
            new_cfg["schedule"] = sched

    if "include_candidates" in form:
        new_cfg["include_candidates"] = str(form["include_candidates"]).strip().lower() in (
            "on", "true", "1", "yes"
        )
    else:
        new_cfg["include_candidates"] = False

    atomic_write(
        config_path(name, repo_root),
        yaml.dump(new_cfg, sort_keys=False, allow_unicode=True),
    )
    return RedirectResponse(f"/agents/{name}", status_code=303)


@router.post("/agents/{name}/prompt")
async def agents_save_prompt(
    request: Request,
    name: str,
    prompt: str = Form(...),
):
    repo_root: Path = request.app.state.repo_root
    meta = load_agent(name, repo_root)
    if meta is None:
        return _not_found(request, name)

    # Normalise trailing newline so git diffs stay clean.
    text = prompt.replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    atomic_write(prompt_path(name, repo_root), text)
    return RedirectResponse(f"/agents/{name}", status_code=303)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _not_found(request: Request, name: str) -> HTMLResponse:
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request, "agents.html",
        {"agents": [], "intervals": VALID_INTERVALS, "not_found": name},
        status_code=404,
    )


def _relative_time(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "never"
    try:
        ts = datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return str(iso_str)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    return f"{months}mo ago"


def _to_list_dict(meta: AgentMeta) -> dict:
    state = meta.state or {}
    last_run_at = state.get("last_run_at")
    schedule = meta.schedule
    interval_s = parse_interval_seconds(schedule)
    return {
        "name": meta.name,
        "description": meta.description,
        "schedule": schedule,
        "interval_seconds": interval_s,
        "last_run_at": last_run_at,
        "last_run_relative": _relative_time(last_run_at),
        "last_status": state.get("last_status"),
        "last_duration_s": state.get("last_duration_s"),
        "last_message": state.get("last_message"),
        "last_job_id": state.get("last_job_id"),
        "has_run_fn": meta.has_run_fn,
        "config_exists": meta.config_exists,
        "prompt_exists": meta.prompt_exists,
    }


def _to_detail_dict(meta: AgentMeta, repo_root: Path) -> dict:
    base = _to_list_dict(meta)
    base.update({
        "config": meta.config,
        "config_path_rel": str(config_path(meta.name, repo_root).relative_to(repo_root)),
        "prompt_path_rel": str(prompt_path(meta.name, repo_root).relative_to(repo_root)),
        "prompt": meta.prompt,
        "state": meta.state,
        "folder": str(meta.folder.relative_to(repo_root)),
    })
    return base
