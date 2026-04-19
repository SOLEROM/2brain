"""wikiLLM — maintains the wiki root (``domains/<domain>/index.md``).

Walks every approved page in a domain, assembles a compact catalog, and
asks the LLM to rewrite the landing page into an informative, densely
wikilink-cross-referenced browse surface for the Wiki tab's "wiki" view.

Reads:  agents/wikiLLM/config.yaml
        agents/wikiLLM/prompt.md
        domains/<d>/schema.md
        domains/<d>/<type>/*.md  (all approved pages)
Writes: domains/<d>/index.md    (atomic)
"""
from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import anthropic

from src.utils import atomic_write, now_iso
from src.validate import parse_frontmatter
from src.web.routes.shared import default_domain

if TYPE_CHECKING:
    from src.agents.registry import AgentMeta
    from src.agents.seen import SeenTracker


SKIP_FILES = {"index.md", "log.md", "schema.md"}
SKIP_PARTS = {"indexes", ".archive"}


def _resolve_domains(meta: "AgentMeta", repo_root: Path) -> list[str]:
    listed = meta.config.get("domains")
    if isinstance(listed, list) and listed:
        return [str(d).strip() for d in listed if str(d).strip()]
    single = str(meta.config.get("domain") or "").strip()
    if single:
        return [single]
    return [default_domain(repo_root)]


def _body_preview(body: str, max_chars: int) -> str:
    """Return the first non-empty paragraph, clipped to max_chars.

    Agents sometimes front-load pages with metadata-ish boilerplate — we
    still clip rather than get clever, so the prompt stays honest about
    what the catalog actually contains.
    """
    text = (body or "").strip()
    if not text:
        return ""
    # Collapse whitespace, prefer the first real paragraph.
    for para in text.split("\n\n"):
        p = " ".join(para.split())
        if p and not p.startswith("#"):
            return p[:max_chars]
    return " ".join(text.split())[:max_chars]


def _iter_approved_pages(domain_dir: Path):
    for md in sorted(domain_dir.rglob("*.md")):
        if any(seg in SKIP_PARTS for seg in md.parts):
            continue
        if md.name in SKIP_FILES:
            continue
        yield md


def _build_catalog(
    domain: str,
    repo_root: Path,
    max_pages: int,
    max_body_chars: int,
    max_context_chars: int,
    include_candidates: bool,
) -> tuple[list[dict], int]:
    """Collect approved (and optionally candidate) pages for the prompt.

    Returns (entries, total_pages_before_trunc). Each entry has the fields
    the prompt references: title, type, path, confidence, tags, updated_at,
    status, body.
    """
    domain_dir = repo_root / "domains" / domain
    entries: list[dict] = []

    if domain_dir.exists():
        for page in _iter_approved_pages(domain_dir):
            fm, body = parse_frontmatter(page)
            title = str(fm.get("title") or "").strip()
            if not title:
                continue
            entries.append({
                "title": title,
                "type": str(fm.get("type") or ""),
                "path": page.relative_to(repo_root).as_posix(),
                "confidence": float(fm.get("confidence", 0.0) or 0.0),
                "tags": [str(t) for t in (fm.get("tags") or [])],
                "updated_at": str(fm.get("updated_at") or ""),
                "status": "approved",
                "body": _body_preview(body, max_body_chars),
            })

    if include_candidates:
        cand_dir = repo_root / "candidates" / domain / "pending"
        if cand_dir.exists():
            for page in sorted(cand_dir.glob("*.md")):
                fm, body = parse_frontmatter(page)
                title = str(fm.get("title") or "").strip()
                if not title:
                    continue
                entries.append({
                    "title": title,
                    "type": str(fm.get("type") or ""),
                    "path": page.relative_to(repo_root).as_posix(),
                    "confidence": float(fm.get("confidence", 0.0) or 0.0),
                    "tags": [str(t) for t in (fm.get("tags") or [])],
                    "updated_at": str(fm.get("updated_at") or ""),
                    "status": "candidate",
                    "body": _body_preview(body, max_body_chars),
                })

    total = len(entries)
    entries.sort(
        key=lambda e: (e["status"] != "approved", -e["confidence"], e["title"].lower()),
    )
    entries = entries[:max_pages]

    # Hard cap on the entire catalog block to keep the prompt bounded even
    # when individual page bodies are long. Trim bodies first, then drop
    # trailing entries if still over budget.
    budget = max_context_chars
    running = 0
    for entry in entries:
        header_len = 120  # rough overhead per entry
        body_budget = max(0, budget - running - header_len)
        if body_budget <= 0:
            entry["body"] = ""
        elif len(entry["body"]) > body_budget:
            entry["body"] = entry["body"][:body_budget]
        running += header_len + len(entry["body"])

    return entries, total


def _render_catalog(entries: list[dict]) -> str:
    if not entries:
        return "(no approved pages yet)"
    lines: list[str] = []
    for e in entries:
        label = "APPROVED" if e["status"] == "approved" else "CANDIDATE"
        tags = ", ".join(e["tags"][:6]) if e["tags"] else ""
        meta = (
            f"type={e['type'] or '—'} | "
            f"confidence={e['confidence']:.2f} | "
            f"updated={e['updated_at'][:10] or '—'}"
        )
        if tags:
            meta += f" | tags={tags}"
        lines.append(f"### [{label}] {e['title']}")
        lines.append(f"path=`{e['path']}`")
        lines.append(meta)
        if e["body"]:
            lines.append("")
            lines.append(e["body"])
        lines.append("")
        lines.append("---")
    return "\n".join(lines)


def _read_schema(domain_dir: Path) -> str:
    p = domain_dir / "schema.md"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _read_current_index(domain_dir: Path) -> str:
    p = domain_dir / "index.md"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _substitute(template: str, **values: str) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


def _validate_index_output(text: str, catalog: list[dict]) -> list[str]:
    """Best-effort sanity checks. Returns a list of warnings (non-fatal).

    We intentionally don't reject outright — a human will see the result in
    the UI and can rerun. But we flag obvious problems so the job message
    carries a heads-up.
    """
    warnings: list[str] = []
    stripped = text.lstrip()
    if stripped.startswith("---"):
        warnings.append("output starts with YAML frontmatter (should be pure markdown)")
    if not stripped.startswith("#"):
        warnings.append("output does not start with an H1 heading")
    if "[[" not in text and catalog:
        warnings.append("no [[wikilinks]] in output (catalog had pages)")
    return warnings


def _generate_index(
    domain: str,
    repo_root: Path,
    prompt_template: str,
    model: str,
    max_tokens: int,
    max_pages: int,
    max_body_chars: int,
    max_context_chars: int,
    include_candidates: bool,
    api_key: str,
) -> dict:
    domain_dir = repo_root / "domains" / domain
    entries, total = _build_catalog(
        domain, repo_root,
        max_pages=max_pages,
        max_body_chars=max_body_chars,
        max_context_chars=max_context_chars,
        include_candidates=include_candidates,
    )
    schema_md = _read_schema(domain_dir)
    current_index = _read_current_index(domain_dir)

    prompt = _substitute(prompt_template, domain=domain, now=now_iso())
    user_msg = (
        f"{prompt}\n\n"
        f"## Domain\n{domain}\n\n"
        f"## Domain schema (`schema.md`)\n\n{schema_md or '(no schema.md)'}\n\n"
        f"## Current `index.md` (for reference — improve, do not slavishly copy)\n\n"
        f"{current_index or '(empty)'}\n\n"
        f"## Catalog — {len(entries)} page(s) "
        f"({'+' if total > len(entries) else ''}{total} total)\n\n"
        f"{_render_catalog(entries)}\n"
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user_msg}],
        )
    except Exception as exc:
        raise RuntimeError(
            f"Claude API error: {exc}\n\n{traceback.format_exc(limit=3)}",
        ) from exc

    text = (message.content[0].text or "").strip()
    if not text:
        raise RuntimeError("Claude returned empty content.")

    # Strip accidental wrapping triple-fence if the model ignored the rule.
    if text.startswith("```") and text.endswith("```"):
        inner = text.strip("`").lstrip("markdown").lstrip("md").strip()
        if inner:
            text = inner

    warnings = _validate_index_output(text, entries)
    footer = (
        "\n\n---\n"
        f"<!-- generated by wikiLLM at {now_iso()} "
        f"from {len(entries)} page(s) -->\n"
    )
    atomic_write(domain_dir / "index.md", text.rstrip() + footer)

    usage = getattr(message, "usage", None)
    tokens_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    tokens_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

    return {
        "domain": domain,
        "pages_included": len(entries),
        "pages_total": total,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "warnings": warnings,
        "output": f"domains/{domain}/index.md",
    }


def run_wiki_llm(
    *,
    meta: "AgentMeta",
    repo_root: Path,
    job_id: str,
    question_override: Optional[str] = None,
    work_scope: str = "all",
    seen: Optional["SeenTracker"] = None,
    **_ignored,
) -> dict:
    if not meta.prompt.strip():
        raise RuntimeError("prompt.md is empty — wikiLLM cannot run without a prompt template.")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — wikiLLM cannot call Claude.")

    from src.web.routes.shared import get_models_settings
    model = str(meta.config.get("model") or get_models_settings(repo_root)["main"])
    max_tokens = int(meta.config.get("max_tokens", 4096))
    max_pages = int(meta.config.get("max_pages", 80))
    max_body_chars = int(meta.config.get("max_body_chars", 400))
    max_context_chars = int(meta.config.get("max_context_chars", 60_000))
    include_candidates = bool(meta.config.get("include_candidates", False))

    domains = _resolve_domains(meta, repo_root)
    if not domains:
        return {
            "message": "No domains configured and none found under domains/.",
            "outputs": [],
            "skipped": True,
        }

    per_domain: list[dict] = []
    errors: list[str] = []
    outputs: list[str] = []

    for domain in domains:
        try:
            result = _generate_index(
                domain=domain,
                repo_root=repo_root,
                prompt_template=meta.prompt,
                model=model,
                max_tokens=max_tokens,
                max_pages=max_pages,
                max_body_chars=max_body_chars,
                max_context_chars=max_context_chars,
                include_candidates=include_candidates,
                api_key=api_key,
            )
            per_domain.append(result)
            outputs.append(result["output"])
        except Exception as exc:
            errors.append(f"{domain}: {type(exc).__name__}: {exc}")

    totals_in = sum(d.get("tokens_in", 0) for d in per_domain)
    totals_out = sum(d.get("tokens_out", 0) for d in per_domain)
    parts = [
        f"Rewrote {len(per_domain)} index(es)",
        f"tokens {totals_in}→{totals_out}",
    ]
    all_warnings = [w for d in per_domain for w in d.get("warnings", [])]
    if all_warnings:
        parts.append(f"{len(all_warnings)} warning(s)")
    if errors:
        parts.append(f"{len(errors)} failed")
    message = " — ".join(parts)
    if errors:
        message += ": " + "; ".join(errors[:3])

    return {
        "message": message,
        "outputs": outputs,
        "domains": [d["domain"] for d in per_domain],
        "per_domain": per_domain,
        "failures": errors,
        "tokens_in": totals_in,
        "tokens_out": totals_out,
    }
