import asyncio
from pathlib import Path
import yaml
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from src.digest import digest_raw

router = APIRouter()


def _list_domains(repo_root: Path) -> list[str]:
    domains_dir = repo_root / "domains"
    if not domains_dir.exists():
        return ["edge-ai"]
    return sorted(
        d.name for d in domains_dir.iterdir()
        if d.is_dir() and (d / "domain.yaml").exists()
    ) or ["edge-ai"]


def _list_raw_sources(repo_root: Path) -> list[dict]:
    raw_dir = repo_root / "inbox" / "raw"
    if not raw_dir.exists():
        return []
    sources = []
    for entry in sorted(raw_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        meta_path = entry / "metadata.yaml"
        if not meta_path.exists():
            continue
        try:
            meta = yaml.safe_load(meta_path.read_text())
        except Exception:
            meta = {}
        sources.append({
            "raw_id": entry.name,
            "title": meta.get("title", entry.name),
            "ingested_at": meta.get("ingested_at", ""),
            "source_type": meta.get("source_type", ""),
            "domain_hint": meta.get("domain_hint", ""),
            "fetch_status": meta.get("fetch_status", ""),
        })
    return sources


@router.get("/digest", response_class=HTMLResponse)
async def digest_form(request: Request, raw_id: str = "", domain: str = ""):
    templates = request.app.state.templates
    repo_root: Path = request.app.state.repo_root
    domains = _list_domains(repo_root)
    sources = _list_raw_sources(repo_root)
    selected_domain = domain or domains[0]
    return templates.TemplateResponse(request, "digest.html", {
        "domain": selected_domain,
        "domains": domains,
        "sources": sources,
        "selected_raw_id": raw_id,
        "result": None,
        "error": None,
    })


@router.post("/digest", response_class=HTMLResponse)
async def digest_submit(
    request: Request,
    raw_id: str = Form(...),
    domain: str = Form(...),
):
    templates = request.app.state.templates
    repo_root: Path = request.app.state.repo_root
    domains = _list_domains(repo_root)
    sources = _list_raw_sources(repo_root)
    error = None
    result = None

    try:
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set — digest requires a Claude API key.")

        def _do_digest():
            return digest_raw(raw_id=raw_id, domain=domain, repo_root=repo_root, api_key=api_key)

        candidates = await asyncio.to_thread(_do_digest)
        result = {"raw_id": raw_id, "domain": domain, "candidates": candidates}
    except Exception as exc:
        error = str(exc)

    return templates.TemplateResponse(request, "digest.html", {
        "domain": domain,
        "domains": domains,
        "sources": sources,
        "result": result,
        "error": error,
        "selected_raw_id": raw_id,
    })
