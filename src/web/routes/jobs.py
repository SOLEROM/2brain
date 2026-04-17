"""View digest / research job records and raw sources."""
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.utils import append_line, now_iso
from src.web.routes.shared import load_yaml

router = APIRouter()

STATE_DIRS = ["queued", "running", "completed", "failed"]


def _safe_name(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and ".." not in name


def _load_jobs(repo_root: Path) -> dict[str, list[dict]]:
    jobs_dir = repo_root / "jobs"
    out: dict[str, list[dict]] = {s: [] for s in STATE_DIRS}
    if not jobs_dir.exists():
        return out
    for state in STATE_DIRS:
        d = jobs_dir / state
        if not d.exists():
            continue
        for path in sorted(d.glob("*.yaml"), reverse=True):
            data = load_yaml(path)
            if not data:
                continue
            data["_filename"] = path.name
            data["_state"] = state
            out[state].append(data)
    return out


def _load_raw_sources(repo_root: Path) -> list[dict]:
    raw_dir = repo_root / "inbox" / "raw"
    if not raw_dir.exists():
        return []
    items = []
    for entry in sorted(raw_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        meta = load_yaml(entry / "metadata.yaml")
        if not meta:
            continue
        items.append({
            "raw_id": entry.name,
            "title": meta.get("title", entry.name),
            "source_type": meta.get("source_type", ""),
            "ingested_at": meta.get("ingested_at", ""),
            "domain_hint": meta.get("domain_hint", ""),
            "url": meta.get("url", ""),
            "fetch_status": meta.get("fetch_status", "ok"),
        })
    return items


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_list(request: Request):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    buckets = _load_jobs(repo_root)
    return templates.TemplateResponse(request, "jobs.html", {
        "buckets": buckets,
        "counts": {k: len(v) for k, v in buckets.items()},
    })


@router.get("/sources", response_class=HTMLResponse)
async def sources_list(request: Request):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    sources = _load_raw_sources(repo_root)
    return templates.TemplateResponse(request, "sources.html", {
        "sources": sources,
    })


@router.post("/sources/{raw_id}/delete")
async def source_delete(request: Request, raw_id: str):
    """Hard-delete a raw source folder (inbox/raw/<raw_id>/)."""
    if not _safe_name(raw_id):
        raise HTTPException(status_code=400, detail="Invalid raw_id")
    repo_root: Path = request.app.state.repo_root
    entry = repo_root / "inbox" / "raw" / raw_id
    if not entry.is_dir():
        raise HTTPException(status_code=404, detail="Raw source not found")
    shutil.rmtree(entry)
    append_line(
        repo_root / "audit" / "ingest.log",
        f"[{now_iso()}] delete-source | {raw_id}",
    )
    return RedirectResponse("/sources", status_code=303)


@router.get("/jobs/{state}/{filename}", response_class=HTMLResponse)
async def job_detail(request: Request, state: str, filename: str):
    """Detail page for a single job, including any persisted event log."""
    if state not in STATE_DIRS:
        raise HTTPException(status_code=400, detail=f"Invalid state: {state}")
    if not _safe_name(filename) or not filename.endswith(".yaml"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    path = repo_root / "jobs" / state / filename
    if not path.exists() or not path.is_file():
        # The job may have just transitioned (running → completed/failed).
        # Find it in any other bucket so auto-refresh lands on the new URL.
        for alt in STATE_DIRS:
            if alt == state:
                continue
            alt_path = repo_root / "jobs" / alt / filename
            if alt_path.exists() and alt_path.is_file():
                return RedirectResponse(f"/jobs/{alt}/{filename}", status_code=303)
        raise HTTPException(status_code=404, detail="Job not found")

    job = load_yaml(path)
    if not job:
        raise HTTPException(status_code=500, detail="Job YAML could not be parsed")

    events_path = path.with_name(filename.replace(".yaml", ".events.jsonl"))
    events: list[dict] = []
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return templates.TemplateResponse(request, "job_detail.html", {
        "state": state,
        "filename": filename,
        "job": job,
        "events": events,
        "events_path_rel": str(events_path.relative_to(repo_root))
            if events_path.exists() else "",
    })


def _delete_job_file(repo_root: Path, state: str, filename: str) -> bool:
    """Delete a single job YAML and its sidecar events file. Silently skips missing."""
    if state not in STATE_DIRS or not _safe_name(filename) or not filename.endswith(".yaml"):
        return False
    path = repo_root / "jobs" / state / filename
    if not path.exists() or not path.is_file():
        return False
    path.unlink()
    events_path = path.with_name(filename.replace(".yaml", ".events.jsonl"))
    if events_path.exists():
        events_path.unlink()
    return True


@router.post("/jobs/bulk-delete")
async def jobs_bulk_delete(request: Request):
    """Delete every job selected via checkboxes.

    Each form value `item` is a "state/filename" string.
    """
    repo_root: Path = request.app.state.repo_root
    form = await request.form()
    items = form.getlist("item")
    deleted = 0
    for raw in items:
        if "/" not in raw:
            continue
        state, filename = raw.split("/", 1)
        if _delete_job_file(repo_root, state, filename):
            deleted += 1
    append_line(
        repo_root / "audit" / "approvals.log",
        f"[{now_iso()}] delete-jobs-bulk | count={deleted}",
    )
    return RedirectResponse("/jobs", status_code=303)


@router.post("/jobs/delete-all")
async def jobs_delete_all(request: Request):
    """Wipe every job record across every state."""
    repo_root: Path = request.app.state.repo_root
    deleted = 0
    jobs_dir = repo_root / "jobs"
    if jobs_dir.exists():
        for state in STATE_DIRS:
            d = jobs_dir / state
            if not d.exists():
                continue
            for p in list(d.glob("*.yaml")):
                if _delete_job_file(repo_root, state, p.name):
                    deleted += 1
    append_line(
        repo_root / "audit" / "approvals.log",
        f"[{now_iso()}] delete-jobs-all | count={deleted}",
    )
    return RedirectResponse("/jobs", status_code=303)


@router.post("/jobs/{state}/delete-all")
async def jobs_delete_all_in_state(request: Request, state: str):
    """Wipe every job record in a single state bucket."""
    if state not in STATE_DIRS:
        raise HTTPException(status_code=400, detail=f"Invalid state: {state}")
    repo_root: Path = request.app.state.repo_root
    deleted = 0
    d = repo_root / "jobs" / state
    if d.exists():
        for p in list(d.glob("*.yaml")):
            if _delete_job_file(repo_root, state, p.name):
                deleted += 1
    append_line(
        repo_root / "audit" / "approvals.log",
        f"[{now_iso()}] delete-jobs-state | state={state} | count={deleted}",
    )
    return RedirectResponse("/jobs", status_code=303)


@router.post("/jobs/{state}/{filename}/delete")
async def job_delete(request: Request, state: str, filename: str):
    """Delete a single job record YAML (and its events sidecar)."""
    if state not in STATE_DIRS:
        raise HTTPException(status_code=400, detail=f"Invalid state: {state}")
    if not _safe_name(filename) or not filename.endswith(".yaml"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    repo_root: Path = request.app.state.repo_root
    if not _delete_job_file(repo_root, state, filename):
        raise HTTPException(status_code=404, detail="Job not found")
    return RedirectResponse("/jobs", status_code=303)


@router.get("/sources/{raw_id}", response_class=HTMLResponse)
async def source_detail(request: Request, raw_id: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    entry = repo_root / "inbox" / "raw" / raw_id
    if not entry.is_dir():
        raise HTTPException(status_code=404, detail="Raw source not found")
    meta = load_yaml(entry / "metadata.yaml")
    source_md = entry / "source.md"
    content = source_md.read_text(encoding="utf-8") if source_md.exists() else ""
    # Keep the preview bounded — these can be huge HTML pages.
    preview = content[:20_000]
    truncated = len(content) > 20_000
    return templates.TemplateResponse(request, "source_detail.html", {
        "raw_id": raw_id,
        "meta": meta,
        "content": preview,
        "truncated": truncated,
    })
