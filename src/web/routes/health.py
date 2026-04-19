"""Health check / lint web endpoint."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.lint import lint_domain
from src.web.routes.shared import list_domains

router = APIRouter()


@router.get("/health/{domain}", response_class=HTMLResponse)
async def health_view(request: Request, domain: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    report = lint_domain(domain, repo_root=repo_root)
    return templates.TemplateResponse(request, "health.html", {
        "domain": domain,
        "domains": list_domains(repo_root),
        "report": report,
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
