"""LLM-powered Ask tab — grounded in the approved wiki (plus optional candidates)."""
from pathlib import Path
from typing import Optional

import markdown
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.query import ASK_SECTIONS, ask_llm, confidence_label
from src.utils import append_line, now_iso

router = APIRouter()

MD_EXTENSIONS = ["tables", "fenced_code", "sane_lists", "nl2br"]


@router.get("/ask/{domain}", response_class=HTMLResponse)
async def ask_page(
    request: Request,
    domain: str,
    q: str = "",
    include_candidates: Optional[str] = None,
):
    repo_root: Path = request.app.state.repo_root
    templates = request.app.state.templates

    include_candidates_bool = include_candidates in ("on", "1", "true", "yes")

    ask_ctx = None
    if q.strip():
        ask_ctx = _run_ask(
            question=q,
            domain=domain,
            repo_root=repo_root,
            include_candidates=include_candidates_bool,
        )

    return templates.TemplateResponse(request, "ask.html", {
        "domain": domain,
        "question": q,
        "include_candidates": include_candidates_bool,
        "ask_ctx": ask_ctx,
    })


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
) -> dict:
    result = ask_llm(
        question=question,
        domain=domain,
        repo_root=repo_root,
        include_candidates=include_candidates,
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
    }
