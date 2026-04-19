"""LLM-powered Ask tab — grounded in the approved wiki (plus optional candidates)."""
from pathlib import Path
from typing import Optional

import markdown
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.query import (
    ASK_ALLOWED_MODELS,
    ASK_SECTIONS,
    ASK_STYLES,
    ASK_STYLE_DEFAULT,
    ask_llm,
    confidence_label,
)
from src.utils import append_line, now_iso

router = APIRouter()

MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "nl2br"]


def _truthy(v: Optional[str]) -> bool:
    return (v or "").lower() in ("on", "1", "true", "yes")


@router.get("/ask/{domain}", response_class=HTMLResponse)
async def ask_page(
    request: Request,
    domain: str,
    q: str = "",
    include_candidates: Optional[str] = None,
):
    templates = request.app.state.templates
    # The page is now a JS-driven chat. Server-side render is just the shell;
    # `q` in the URL is auto-submitted client-side so shareable links still work.
    return templates.TemplateResponse(request, "ask.html", {
        "domain": domain,
        "prefill_question": q,
        "prefill_include_candidates": _truthy(include_candidates),
        "ask_styles": list(ASK_STYLES.keys()),
        "ask_style_default": ASK_STYLE_DEFAULT,
        "ask_models": sorted(ASK_ALLOWED_MODELS),
    })


def _parse_float(v: Optional[str]) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_int(v: Optional[str]) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@router.post("/ask/{domain}/api")
async def ask_api(
    request: Request,
    domain: str,
    q: str = Form(...),
    include_candidates: Optional[str] = Form(None),
    style: Optional[str] = Form(None),
    temperature: Optional[str] = Form(None),
    max_tokens: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
):
    """JSON endpoint used by the chat UI."""
    repo_root: Path = request.app.state.repo_root
    if not q.strip():
        raise HTTPException(status_code=400, detail="Empty question")
    ctx = _run_ask(
        question=q,
        domain=domain,
        repo_root=repo_root,
        include_candidates=_truthy(include_candidates),
        style=(style or None),
        temperature=_parse_float(temperature),
        max_tokens=_parse_int(max_tokens),
        model=(model or None),
    )
    return JSONResponse(ctx)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel_to_repo(abs_path: str, repo_root: Path) -> str:
    try:
        return str(Path(abs_path).resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return abs_path


def _candidate_link(rel_path: str, domain: str) -> str:
    parts = rel_path.split("/")
    if len(parts) >= 3 and parts[0] == "candidates":
        return f"/candidates/{domain}/{parts[-1]}"
    return f"/candidates/{domain}"


def _run_ask(
    *,
    question: str,
    domain: str,
    repo_root: Path,
    include_candidates: bool,
    style: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> dict:
    result = ask_llm(
        question=question,
        domain=domain,
        repo_root=repo_root,
        include_candidates=include_candidates,
        style=style,
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
    )

    sections_rendered = {}
    for name in ASK_SECTIONS:
        raw = result.sections.get(name, "None") or "None"
        if raw.strip().lower() == "none":
            sections_rendered[name] = {"raw": "None", "html": "", "is_empty": True}
        else:
            sections_rendered[name] = {
                "raw": raw,
                "html": markdown.markdown(raw, extensions=MD_EXTENSIONS),
                "is_empty": False,
            }

    cited = []
    for m in result.cited_pages:
        rel_path = _rel_to_repo(m.path, repo_root)
        is_approved = m.status == "approved" and rel_path.startswith("domains/")
        link = (
            f"/wiki/{domain}/page/{rel_path}" if is_approved
            else _candidate_link(rel_path, domain)
        )
        cited.append({
            "title": m.title,
            "rel_path": rel_path,
            "status": m.status,
            "confidence": m.confidence,
            "confidence_label": confidence_label(m.confidence),
            "is_approved": is_approved,
            "link": link,
            "type": m.type,
        })

    try:
        q_short = (question or "").replace("\n", " ").strip()[:80]
        line = (
            f"{now_iso()} ask | domain={domain} | "
            f"q={q_short!r} | cited={len(cited)} | "
            f"tokens={result.tokens_in}/{result.tokens_out} | "
            f"scope={result.scope}"
        )
        append_line(repo_root / "audit" / "agent-actions.log", line)
    except Exception:
        pass

    return {
        "question": result.question,
        "error": result.error,
        "sections": sections_rendered,
        "cited": cited,
        "model": result.model,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "duration_s": result.duration_s,
        "scope": result.scope,
        "style": result.style,
        "temperature": result.temperature,
        "max_tokens": result.max_tokens,
    }
