from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from src.validate import parse_frontmatter
from src.query import confidence_label
import markdown

router = APIRouter()


@router.get("/wiki/{domain}", response_class=HTMLResponse)
async def wiki_browse(request: Request, domain: str):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates
    domain_dir = repo_root / "domains" / domain
    pages = []
    if domain_dir.exists():
        for md_file in sorted(domain_dir.rglob("*.md")):
            if "indexes" in str(md_file) or md_file.name in ("index.md", "log.md", "schema.md"):
                continue
            fm, _ = parse_frontmatter(md_file)
            if fm.get("title"):
                pages.append({
                    "title": fm["title"],
                    "path": str(md_file.relative_to(repo_root)),
                    "type": fm.get("type", ""),
                    "status": fm.get("status", ""),
                    "confidence": fm.get("confidence", 0.0),
                    "confidence_label": confidence_label(float(fm.get("confidence", 0.0))),
                })
    return templates.TemplateResponse(request, "wiki_browse.html", {
        "domain": domain, "pages": pages
    })
