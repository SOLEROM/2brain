from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from src.approval import list_pending, approve_candidate, reject_candidate
from src.validate import parse_frontmatter
from src.query import confidence_label
import markdown

router = APIRouter()


@router.get("/candidates/{domain}", response_class=HTMLResponse)
async def candidates_list(request: Request, domain: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    pending = list_pending(domain, repo_root=repo_root)
    items = []
    for fname in pending:
        path = repo_root / "candidates" / domain / "pending" / fname
        fm, _ = parse_frontmatter(path)
        items.append({
            "filename": fname,
            "title": fm.get("title", fname),
            "type": fm.get("type", ""),
            "confidence": fm.get("confidence", 0.0),
            "confidence_label": confidence_label(float(fm.get("confidence", 0.0))),
            "operation": fm.get("candidate_operation", "create"),
            "tags": fm.get("tags", []),
        })
    return templates.TemplateResponse(request, "candidates_list.html", {
        "domain": domain, "items": items
    })


@router.get("/candidates/{domain}/{filename}", response_class=HTMLResponse)
async def candidate_review(request: Request, domain: str, filename: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    path = repo_root / "candidates" / domain / "pending" / filename
    fm, body = parse_frontmatter(path)
    rendered_body = markdown.markdown(body, extensions=["tables", "fenced_code"])
    return templates.TemplateResponse(request, "candidate_review.html", {
        "domain": domain,
        "filename": filename,
        "fm": fm,
        "confidence_label": confidence_label(float(fm.get("confidence", 0.0))),
        "body_html": rendered_body,
        "raw_content": path.read_text(),
    })


@router.post("/candidates/{domain}/{filename}/approve")
async def approve_action(
    request: Request,
    domain: str,
    filename: str,
    reviewed_by: str = Form(default="user"),
):
    repo_root: Path = request.app.state.repo_root
    approve_candidate(filename, domain, reviewed_by=reviewed_by, repo_root=repo_root)
    return RedirectResponse(f"/candidates/{domain}", status_code=303)


@router.post("/candidates/{domain}/{filename}/reject")
async def reject_action(request: Request, domain: str, filename: str):
    repo_root: Path = request.app.state.repo_root
    reject_candidate(filename, domain, repo_root=repo_root)
    return RedirectResponse(f"/candidates/{domain}", status_code=303)
