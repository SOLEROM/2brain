"""deepSearch agent — investigates a research question across the wiki and
produces a deep-research-report candidate page for human review.

Reads:  agents/deepSearch/config.yaml   (question, domain, model, budgets)
        agents/deepSearch/prompt.md      (LLM prompt template)
Writes: candidates/<domain>/pending/cand_<...>.md  (the draft report)
        jobs/completed/job_<...>.yaml                (job record, via runner)
        audit/agent-actions.log                      (audit line, via runner)
"""
from __future__ import annotations

import os
import tempfile
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import anthropic

from src.digest import (
    build_candidate_id,
    extract_page_from_response,
    parse_frontmatter_str,
    write_candidate,
)

if TYPE_CHECKING:
    from src.agents.registry import AgentMeta
from src.query import collect_ask_context
from src.utils import now_iso, slug_from_title
from src.validate import validate_frontmatter
from src.web.routes.shared import default_domain


def _validate_page_text(page_text: str):
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8",
    ) as tf:
        tf.write(page_text)
        tf_path = tf.name
    try:
        return validate_frontmatter(Path(tf_path))
    finally:
        os.unlink(tf_path)


def _resolve_domain(meta: "AgentMeta", repo_root: Path) -> str:
    configured = (meta.config.get("domain") or "").strip()
    if configured:
        return configured
    return default_domain(repo_root)


def _render_context_block(pages) -> str:
    if not pages:
        return "(no wiki pages matched)"
    blocks: list[str] = []
    for p in pages:
        label = "APPROVED" if p.status == "approved" else "CANDIDATE"
        blocks.append(
            f"### [{label}] {p.title}  path=`{p.path}`  confidence={p.confidence:.2f}\n"
            f"{p.body}\n\n---"
        )
    return "\n\n".join(blocks)


def _substitute(template: str, **values: str) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


def run_deep_search(
    *,
    meta: "AgentMeta",
    repo_root: Path,
    job_id: str,
    question_override: Optional[str] = None,
) -> dict:
    """Execute one deep-search run. Returns {message, outputs, ...}.

    Raises on unrecoverable errors so the runner can record them.
    """
    question = (question_override or meta.config.get("question") or "").strip()
    if not question:
        raise ValueError("No research question configured. Set `question` in config.yaml or pass an override.")

    domain = _resolve_domain(meta, repo_root)
    model = str(meta.config.get("model") or "claude-sonnet-4-6")
    max_tokens = int(meta.config.get("max_tokens", 4096))
    max_pages = int(meta.config.get("max_pages", 16))
    max_chars = int(meta.config.get("max_context_chars", 60_000))
    include_candidates = bool(meta.config.get("include_candidates", True))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — deepSearch cannot call Claude.")

    if not meta.prompt.strip():
        raise RuntimeError("prompt.md is empty — agent cannot run without a prompt template.")

    pages = collect_ask_context(
        question=question,
        domain=domain,
        repo_root=repo_root,
        include_candidates=include_candidates,
        max_pages=max_pages,
        max_chars=max_chars,
    )

    candidate_id = build_candidate_id(f"deep-research {slug_from_title(question)[:40]}", question)
    prompt = _substitute(
        meta.prompt,
        domain=domain,
        now=now_iso(),
        candidate_id=candidate_id,
    )
    user_msg = (
        f"{prompt}\n\n"
        f"## Research Question\n{question}\n\n"
        f"## Wiki pages (ranked by relevance)\n\n{_render_context_block(pages)}\n"
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        raise RuntimeError(f"Claude API error: {exc}\n\n{traceback.format_exc(limit=3)}") from exc

    text = (message.content[0].text or "").strip()
    if not text:
        raise RuntimeError("Claude returned empty content.")

    page_text = extract_page_from_response(text)
    result = _validate_page_text(page_text)
    if not result.valid:
        raise RuntimeError(
            "Frontmatter invalid in deepSearch output: " + "; ".join(result.errors)
        )

    fm, _ = parse_frontmatter_str(page_text)
    cand_filename = write_candidate(page_text, domain, repo_root)

    usage = getattr(message, "usage", None)
    tokens_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    tokens_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

    return {
        "message": (
            f"Filed deep-research-report → candidates/{domain}/pending/{cand_filename} "
            f"(tokens {tokens_in}→{tokens_out}, pages={len(pages)})"
        ),
        "outputs": [cand_filename],
        "candidate_filename": cand_filename,
        "title": fm.get("title", ""),
        "target_path": fm.get("target_path", ""),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "domain": domain,
    }
