from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from src.query import search_pages, confidence_label

router = APIRouter()


@router.get("/query/{domain}", response_class=HTMLResponse)
async def query_page(request: Request, domain: str, q: str = ""):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    results = []
    if q:
        matches = search_pages(q, domain, repo_root=repo_root)
        for m in matches:
            results.append({
                "title": m.title,
                "path": m.path,
                "status": m.status,
                "confidence": m.confidence,
                "confidence_label": confidence_label(m.confidence),
                "snippet": m.snippet,
                "type": m.type,
            })
    return templates.TemplateResponse("query.html", {
        "request": request, "domain": domain, "query": q, "results": results
    })
