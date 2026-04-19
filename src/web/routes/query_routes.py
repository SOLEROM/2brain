"""Query tab — keyword search with filters over approved + candidate pages."""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from src.query import (
    _load_pages,
    confidence_label,
    search_pages,
)

router = APIRouter()


@router.get("/query/{domain}", response_class=HTMLResponse)
async def query_page(
    request: Request,
    domain: str,
    q: str = "",
    type: list[str] = Query(default_factory=list),
    tag: list[str] = Query(default_factory=list),
    status: list[str] = Query(default_factory=list),
    min_conf: Optional[float] = None,
    scope: str = "all",
):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates

    search_include_candidates = scope != "approved"

    results = _run_search(
        q=q,
        domain=domain,
        repo_root=repo_root,
        include_candidates=search_include_candidates,
        types=type,
        tags=tag,
        statuses=status,
        min_conf=min_conf,
    )

    facets = _collect_facets(domain, repo_root, include_candidates=True)

    return templates.TemplateResponse(request, "query.html", {
        "domain": domain,
        "query": q,
        "results": results,
        "filters": {
            "types": list(type or []),
            "tags": list(tag or []),
            "statuses": list(status or []),
            "min_conf": min_conf,
            "scope": scope,
        },
        "facets": facets,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel_to_repo(abs_path: str, repo_root: Path) -> str:
    try:
        return str(Path(abs_path).resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return abs_path


def _run_search(
    *,
    q: str,
    domain: str,
    repo_root: Path,
    include_candidates: bool,
    types: list[str],
    tags: list[str],
    statuses: list[str],
    min_conf: Optional[float],
) -> list[dict]:
    matches = search_pages(
        q,
        domain,
        repo_root=repo_root,
        include_candidates=include_candidates,
        types=types or None,
        tags=tags or None,
        statuses=statuses or None,
        min_confidence=min_conf,
    )
    out: list[dict] = []
    for m in matches:
        rel_path = _rel_to_repo(m.path, repo_root)
        out.append({
            "title": m.title,
            "path": m.path,
            "rel_path": rel_path,
            "is_approved": m.status == "approved" and rel_path.startswith("domains/"),
            "status": m.status,
            "confidence": m.confidence,
            "confidence_label": confidence_label(m.confidence),
            "snippet": m.snippet,
            "type": m.type,
            "tags": m.tags,
        })
    return out


def _collect_facets(domain: str, repo_root: Path, include_candidates: bool) -> dict:
    pages = _load_pages(domain, repo_root, include_candidates=include_candidates)
    types: set[str] = set()
    tags: set[str] = set()
    statuses: set[str] = set()
    for _, fm, _ in pages:
        if fm.get("type"):
            types.add(str(fm["type"]))
        for t in (fm.get("tags") or []):
            if t:
                tags.add(str(t))
        if fm.get("status"):
            statuses.add(str(fm["status"]))
    return {
        "types": sorted(types),
        "tags": sorted(tags, key=str.lower),
        "statuses": sorted(statuses),
    }
