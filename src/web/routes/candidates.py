from pathlib import Path

import markdown
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.approval import approve_candidate, list_pending, reject_candidate
from src.query import confidence_label
from src.utils import atomic_write, append_line, now_iso
from src.validate import parse_frontmatter

CANDIDATE_BUCKETS = ("pending", "rejected", "archived")

router = APIRouter()

MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "nl2br"]


@router.get("/candidates/{domain}", response_class=HTMLResponse)
async def candidates_list(request: Request, domain: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    pending = list_pending(domain, repo_root=repo_root)
    items = []
    for fname in pending:
        path = repo_root / "candidates" / domain / "pending" / fname
        fm, _ = parse_frontmatter(path)
        conf = float(fm.get("confidence", 0.0) or 0.0)
        items.append({
            "filename": fname,
            "title": fm.get("title", fname),
            "type": fm.get("type", ""),
            "confidence": conf,
            "confidence_label": confidence_label(conf),
            "operation": fm.get("candidate_operation", "create"),
            "tags": fm.get("tags", []) or [],
        })
    return templates.TemplateResponse(request, "candidates_list.html", {
        "domain": domain, "items": items,
    })


@router.get("/candidates/{domain}/{filename}", response_class=HTMLResponse)
async def candidate_review(request: Request, domain: str, filename: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    path = _require_candidate(repo_root, domain, filename)
    fm, body = parse_frontmatter(path)
    rendered_body = markdown.markdown(body, extensions=MD_EXTENSIONS)
    raw_content = path.read_text(encoding="utf-8")
    conf = float(fm.get("confidence", 0.0) or 0.0)
    return templates.TemplateResponse(request, "candidate_review.html", {
        "domain": domain,
        "filename": filename,
        "fm": fm,
        "confidence": conf,
        "confidence_label": confidence_label(conf),
        "body_html": rendered_body,
        "raw_content": raw_content,
    })


@router.post("/candidates/{domain}/{filename}/approve")
async def approve_action(
    request: Request,
    domain: str,
    filename: str,
    reviewed_by: str = Form(default="user"),
    drop_raw: str = Form(default=""),
):
    repo_root: Path = request.app.state.repo_root
    _require_candidate(repo_root, domain, filename)
    try:
        approve_candidate(
            filename, domain,
            reviewed_by=reviewed_by,
            repo_root=repo_root,
            drop_raw=bool(drop_raw),
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/candidates/{domain}", status_code=303)


@router.post("/candidates/{domain}/{filename}/reject")
async def reject_action(
    request: Request,
    domain: str,
    filename: str,
    reason: str = Form(default=""),
):
    repo_root: Path = request.app.state.repo_root
    _require_candidate(repo_root, domain, filename)
    reject_candidate(filename, domain, reason=reason, repo_root=repo_root)
    return RedirectResponse(f"/candidates/{domain}", status_code=303)


@router.post("/candidates/{domain}/{filename}/edit")
async def edit_action(
    request: Request,
    domain: str,
    filename: str,
    raw_content: str = Form(...),
):
    """Overwrite the candidate file with edited content, then redirect to review."""
    repo_root: Path = request.app.state.repo_root
    path = _require_candidate(repo_root, domain, filename)
    atomic_write(path, raw_content)
    return RedirectResponse(f"/candidates/{domain}/{filename}", status_code=303)


def _require_candidate(repo_root: Path, domain: str, filename: str) -> Path:
    path = repo_root / "candidates" / domain / "pending" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Candidate not found: {filename}")
    return path


@router.post("/candidates/{domain}/{bucket}/{filename}/delete")
async def delete_candidate(
    request: Request,
    domain: str,
    bucket: str,
    filename: str,
):
    """Hard-delete a candidate file from pending/rejected/archived."""
    if bucket not in CANDIDATE_BUCKETS:
        raise HTTPException(status_code=400, detail=f"Invalid bucket: {bucket}")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    repo_root: Path = request.app.state.repo_root
    path = repo_root / "candidates" / domain / bucket / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Candidate not found: {filename}")
    path.unlink()

    audit = repo_root / "audit" / "approvals.log"
    append_line(audit, f"[{now_iso()}] delete-candidate | {domain}/{bucket}/{filename}")
    redirect = request.headers.get("referer") or f"/candidates/{domain}"
    return RedirectResponse(redirect, status_code=303)
