"""Health check / lint web endpoint."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from src.lint import lint_domain
from src.web.routes.shared import list_domains

router = APIRouter()


def _rawlist_urls(repo_root: Path) -> list[str]:
    """Read audit/rawlist.log and return URLs in ingest order, deduped.

    Each line format: ``<iso_ts>\\t<raw_id>\\t<url>\\t<title>``.
    """
    path = repo_root / "audit" / "rawlist.log"
    if not path.exists():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        url = parts[2].strip()
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


@router.get("/health/{domain}", response_class=HTMLResponse)
async def health_view(request: Request, domain: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    report = lint_domain(domain, repo_root=repo_root)
    return templates.TemplateResponse(request, "health.html", {
        "domain": domain,
        "domains": list_domains(repo_root),
        "report": report,
        "rawlist_count": len(_rawlist_urls(repo_root)),
        "summary": {
            "low_confidence": len(report.low_confidence_pages),
            "contradictions": len(report.unresolved_contradictions),
            "orphans": len(report.orphans),
            "stale_pages": len(report.stale_pages),
            "stuck_jobs": len(report.stuck_jobs),
            "stale_candidates": len(report.stale_candidates),
            "index_mismatches": len(report.index_mismatches),
        },
    })


@router.post("/health/{domain}/run")
async def health_run(request: Request, domain: str):
    return RedirectResponse(f"/health/{domain}", status_code=303)


@router.get("/export/rawlist.txt", response_class=PlainTextResponse)
async def export_rawlist(request: Request):
    """Download every ingested URL, deduped, one per line.

    Sourced from ``audit/rawlist.log`` so the history survives raw-folder
    deletion (e.g. the "delete raw after digest" option).
    """
    repo_root: Path = request.app.state.repo_root
    urls = _rawlist_urls(repo_root)
    body = "\n".join(urls) + ("\n" if urls else "")
    return PlainTextResponse(
        body,
        headers={"Content-Disposition": 'attachment; filename="rawlist.txt"'},
    )
