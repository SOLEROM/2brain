from pathlib import Path

import markdown
import yaml
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.query import confidence_label
from src.utils import append_domain_log, append_line, atomic_write, now_iso
from src.validate import parse_frontmatter
from src.web.routes.shared import list_domains

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


_METADATA_FILES = {"index.md", "log.md", "schema.md", "domain.yaml"}


@router.post("/wiki/{domain}/move")
async def wiki_move(
    request: Request,
    domain: str,
    rel_path: str = Form(...),
    target_domain: str = Form(...),
):
    """On-demand move of an approved page to another domain.

    Preserves the subpath under `domains/<domain>/` (e.g. `concepts/foo.md`),
    rewrites the `domain` frontmatter field, and logs the operation.
    """
    repo_root: Path = request.app.state.repo_root

    src = (repo_root / rel_path).resolve()
    src_base = (repo_root / "domains" / domain).resolve()
    try:
        src.relative_to(src_base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid source path")
    if src.name in _METADATA_FILES:
        raise HTTPException(status_code=400, detail="Refusing to move domain metadata file")
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=404, detail="Page not found")

    known = list_domains(repo_root)
    if target_domain not in known:
        raise HTTPException(status_code=400, detail=f"Unknown target domain: {target_domain}")
    if target_domain == domain:
        raise HTTPException(status_code=400, detail="Target domain must differ from source")

    src_rel = src.relative_to(repo_root)
    parts = list(src_rel.parts)
    parts[1] = target_domain
    new_rel = Path(*parts)
    tgt = (repo_root / new_rel).resolve()
    tgt_base = (repo_root / "domains" / target_domain).resolve()
    try:
        tgt.relative_to(tgt_base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target path")
    if tgt.exists():
        raise HTTPException(status_code=409, detail=f"Target already exists: {new_rel}")

    fm, body = parse_frontmatter(src)
    fm["domain"] = target_domain
    fm["updated_at"] = now_iso()
    content = (
        "---\n"
        + yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
        + "---\n\n"
        + body
    )
    atomic_write(tgt, content)
    src.unlink()

    title = fm.get("title", src.name)
    append_domain_log(
        repo_root, domain, "move-out",
        f"{title} → domains/{target_domain}/",
    )
    append_domain_log(
        repo_root, target_domain, "move-in",
        f"{title} ← domains/{domain}/",
    )
    append_line(
        repo_root / "audit" / "approvals.log",
        f"[{now_iso()}] move-page | {rel_path} → {new_rel.as_posix()}",
    )

    return RedirectResponse(
        f"/wiki/{target_domain}/page/{new_rel.as_posix()}",
        status_code=303,
    )


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
