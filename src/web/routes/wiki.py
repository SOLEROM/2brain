from pathlib import Path

import markdown
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.query import confidence_label
from src.utils import append_domain_log, append_line, now_iso
from src.validate import parse_frontmatter

router = APIRouter()

MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "nl2br"]


@router.get("/wiki/{domain}", response_class=HTMLResponse)
async def wiki_browse(request: Request, domain: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    domain_dir = repo_root / "domains" / domain

    pages = []
    by_type: dict[str, list[dict]] = {}
    all_tags: set[str] = set()
    if domain_dir.exists():
        for md_file in sorted(domain_dir.rglob("*.md")):
            if "indexes" in md_file.parts or ".archive" in md_file.parts:
                continue
            if md_file.name in ("index.md", "log.md", "schema.md"):
                continue
            fm, _ = parse_frontmatter(md_file)
            if not fm.get("title"):
                continue
            conf = float(fm.get("confidence", 0.0) or 0.0)
            tags = [str(t) for t in (fm.get("tags") or [])]
            all_tags.update(tags)
            entry = {
                "title": fm["title"],
                "rel_path": str(md_file.relative_to(repo_root)),
                "type": fm.get("type", ""),
                "status": fm.get("status", ""),
                "confidence": conf,
                "confidence_label": confidence_label(conf),
                "tags": tags,
                "created_at": str(fm.get("created_at", "") or ""),
                "updated_at": str(fm.get("updated_at", "") or ""),
            }
            pages.append(entry)
            by_type.setdefault(entry["type"] or "other", []).append(entry)

    return templates.TemplateResponse(request, "wiki_browse.html", {
        "domain": domain,
        "pages": pages,
        "by_type": by_type,
        "all_tags": sorted(all_tags),
    })


@router.get("/wiki/{domain}/page/{rel_path:path}", response_class=HTMLResponse)
async def wiki_page(request: Request, domain: str, rel_path: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates

    # Security: must resolve under domains/<domain>/
    target = (repo_root / rel_path).resolve()
    base = (repo_root / "domains" / domain).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid page path")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Page not found")

    fm, body = parse_frontmatter(target)
    conf = float(fm.get("confidence", 0.0) or 0.0)
    rendered = markdown.markdown(body, extensions=MD_EXTENSIONS)
    return templates.TemplateResponse(request, "wiki_page.html", {
        "domain": domain,
        "fm": fm,
        "body_html": rendered,
        "rel_path": rel_path,
        "confidence": conf,
        "confidence_label": confidence_label(conf),
    })


@router.post("/wiki/{domain}/delete")
async def wiki_delete(request: Request, domain: str, rel_path: str = Form(...)):
    """Hard-delete an approved page under domains/<domain>/."""
    repo_root: Path = request.app.state.repo_root
    target = (repo_root / rel_path).resolve()
    base = (repo_root / "domains" / domain).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid page path")
    if target.name in ("index.md", "log.md", "schema.md", "domain.yaml"):
        raise HTTPException(status_code=400, detail="Refusing to delete domain metadata file")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Page not found")

    fm, _ = parse_frontmatter(target)
    title = fm.get("title", target.name)
    target.unlink()
    append_domain_log(repo_root, domain, "delete", title)
    append_line(
        repo_root / "audit" / "approvals.log",
        f"[{now_iso()}] delete-page | {domain} | {rel_path}",
    )
    return RedirectResponse(f"/wiki/{domain}", status_code=303)
