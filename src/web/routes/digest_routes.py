import asyncio
import json
import os
import queue
import threading
import traceback
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from src.digest import digest_raw
from src.utils import now_iso
from src.validate import parse_frontmatter
from src.web.routes.shared import list_domains, load_yaml

router = APIRouter()

# Sentinel used on the internal event queue to signal stream completion.
_STREAM_END = object()


def _raw_ids_awaiting_review(repo_root: Path) -> set[str]:
    """Raw IDs already cited by a candidate in any domain's pending queue.

    These sources have advanced to the Review stage and should be hidden from
    the digest picker so we don't re-digest them by accident.
    """
    out: set[str] = set()
    candidates_root = repo_root / "candidates"
    if not candidates_root.exists():
        return out
    for domain_dir in candidates_root.iterdir():
        pending = domain_dir / "pending"
        if not pending.is_dir():
            continue
        for md in pending.glob("*.md"):
            fm, _ = parse_frontmatter(md)
            for rid in (fm.get("raw_ids") or []):
                if rid:
                    out.add(str(rid))
    return out


def _list_raw_sources(repo_root: Path) -> list[dict]:
    raw_dir = repo_root / "inbox" / "raw"
    if not raw_dir.exists():
        return []
    skip = _raw_ids_awaiting_review(repo_root)
    sources = []
    for entry in sorted(raw_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        if entry.name in skip:
            continue
        meta = load_yaml(entry / "metadata.yaml")
        if not meta:
            continue
        sources.append({
            "raw_id": entry.name,
            "title": meta.get("title", entry.name),
            "ingested_at": meta.get("ingested_at", ""),
            "source_type": meta.get("source_type", ""),
            "domain_hint": meta.get("domain_hint", ""),
            "fetch_status": meta.get("fetch_status", ""),
        })
    return sources


def _list_running_digests(repo_root: Path) -> list[dict]:
    """Return in-flight digest jobs from jobs/running/ for the "Show log" UI."""
    d = repo_root / "jobs" / "running"
    if not d.exists():
        return []
    out: list[dict] = []
    for p in sorted(d.glob("*.yaml")):
        data = load_yaml(p)
        if not data or data.get("job_type") != "digest":
            continue
        out.append({
            "job_id": data.get("job_id", p.stem),
            "filename": p.name,
            "input": data.get("input", ""),
            "domain": data.get("domain", ""),
            "started_at": data.get("started_at", ""),
            "heartbeat_at": data.get("heartbeat_at", ""),
        })
    return out


def _render(
    request: Request,
    *,
    domain: str,
    selected_raw_id: str = "",
    result: Optional[dict] = None,
    error: Optional[str] = None,
) -> HTMLResponse:
    templates = request.app.state.templates
    repo_root: Path = request.app.state.repo_root
    return templates.TemplateResponse(request, "digest.html", {
        "domain": domain,
        "sources": _list_raw_sources(repo_root),
        "running_jobs": _list_running_digests(repo_root),
        "selected_raw_id": selected_raw_id,
        "result": result,
        "error": error,
    })


def _session_domain(request: Request) -> str:
    return getattr(request.state, "current_domain", None) or list_domains(
        request.app.state.repo_root,
    )[0]


@router.get("/digest", response_class=HTMLResponse)
async def digest_form(request: Request, raw_id: str = "", domain: str = ""):
    """GET /digest. Optional ?domain=... overrides the session domain (and persists via cookie).

    Used by "Digest again" links from job records so the retry lands on the
    right domain.
    """
    repo_root: Path = request.app.state.repo_root
    resolved = _session_domain(request)
    set_cookie_for: Optional[str] = None
    if domain and domain in list_domains(repo_root):
        resolved = domain
        set_cookie_for = domain
    resp = _render(request, domain=resolved, selected_raw_id=raw_id)
    if set_cookie_for:
        resp.set_cookie(
            "2brain-domain", set_cookie_for,
            max_age=2_592_000, samesite="lax", path="/",
        )
    return resp


@router.post("/digest", response_class=HTMLResponse)
async def digest_submit(
    request: Request,
    raw_id: str = Form(...),
):
    """Non-streaming fallback: runs digest synchronously and renders the page."""
    repo_root: Path = request.app.state.repo_root
    domain = _session_domain(request)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _render(
            request,
            domain=domain,
            selected_raw_id=raw_id,
            error="ANTHROPIC_API_KEY is not set — digest requires a Claude API key.",
        )

    try:
        candidates = await asyncio.to_thread(
            digest_raw, raw_id=raw_id, domain=domain,
            repo_root=repo_root, api_key=api_key,
        )
        return _render(
            request,
            domain=domain,
            selected_raw_id=raw_id,
            result={"raw_id": raw_id, "domain": domain, "candidates": candidates},
        )
    except Exception as exc:
        return _render(request, domain=domain, selected_raw_id=raw_id, error=str(exc))


@router.get("/digest/stream")
async def digest_stream(request: Request, raw_id: str, domain: str):
    """Run digest and stream per-step events as Server-Sent Events.

    Each event is a JSON blob with keys ts, level, step, message, plus any
    extras emitted by digest_raw. An SSE `event: end` is sent when done.
    """
    repo_root: Path = request.app.state.repo_root
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    q: "queue.Queue" = queue.Queue()

    def push(evt: dict) -> None:
        q.put(evt)

    def run() -> None:
        try:
            digest_raw(
                raw_id=raw_id, domain=domain,
                repo_root=repo_root, api_key=api_key,
                on_event=push,
            )
        except Exception as exc:
            push({
                "ts": now_iso(),
                "level": "error",
                "step": "crash",
                "message": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })
        finally:
            q.put(_STREAM_END)

    threading.Thread(target=run, daemon=True).start()

    async def event_stream():
        loop = asyncio.get_event_loop()
        # Keepalive so proxies don't time out during long Claude calls.
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(
                    loop.run_in_executor(None, q.get), timeout=15.0,
                )
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if item is _STREAM_END:
                yield "event: end\ndata: {}\n\n"
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
