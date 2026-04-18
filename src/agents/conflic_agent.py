"""conflicAgent — scans the wiki for conflicting facts across pages.

Purpose: surface claims that disagree or are mutually exclusive so the human
can arbitrate before the wrong assumption propagates into downstream
reasoning. This is distinct from `lintAgent`, which only regenerates the
`indexes/contradictions.md` index from existing inline `[!contradiction]`
blocks. conflicAgent actively *discovers* conflicts that have not yet been
annotated — using the LLM to spot semantic disagreement.

Reads:  agents/conflicAgent/config.yaml  (domain, model, budgets, thresholds)
        agents/conflicAgent/prompt.md     (detection instructions + examples)
        domains/<d>/                      (approved wiki + optional candidates)
Writes: domains/<d>/reports/contradictions/<slug>.md  (one page per detected
                                                        conflict, status=candidate,
                                                        type=contradiction-note)
        domains/<d>/log.md                (append-only log entry)
        agents/conflicAgent/seen.json     (conflict fingerprints, so re-runs
                                            don't re-file the same conflict)
        jobs/completed/job_<...>.yaml     (agent-run record, via runner)

Manual-only by design — scheduled firing is disabled in config.yaml and
should stay that way. Conflict detection is a deliberate review activity,
not background hygiene.
"""
from __future__ import annotations

import os
import re
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import anthropic
import yaml

from src.digest import build_candidate_id
from src.query import collect_ask_context
from src.utils import (
    append_domain_log,
    atomic_write,
    hash8,
    now_iso,
    slug_from_title,
)

if TYPE_CHECKING:
    from src.agents.registry import AgentMeta
    from src.agents.seen import SeenTracker


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_YAML_FENCE_RE = re.compile(r"```(?:yaml|yml)?\s*\n(.*?)```", re.DOTALL)


def _extract_yaml_block(text: str) -> str:
    m = _YAML_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _parse_conflicts(text: str) -> list[dict]:
    """Parse the LLM's response into a list of conflict dicts."""
    block = _extract_yaml_block(text)
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Failed to parse LLM response as YAML: {exc}") from exc

    if isinstance(data, dict) and "conflicts" in data:
        data = data["conflicts"]
    if data is None:
        return []
    if not isinstance(data, list):
        raise RuntimeError(
            f"Expected a YAML list of conflicts, got {type(data).__name__}."
        )
    return [c for c in data if isinstance(c, dict)]


def _normalize(conflict: dict, min_severity: float) -> Optional[dict]:
    """Clean one conflict dict. Returns None if required fields are missing
    or severity is below the configured threshold."""
    page_a = str(conflict.get("page_a") or "").strip()
    page_b = str(conflict.get("page_b") or "").strip()
    claim_a = str(conflict.get("claim_a") or "").strip()
    claim_b = str(conflict.get("claim_b") or "").strip()
    if not (page_a and page_b and claim_a and claim_b):
        return None

    try:
        severity = float(conflict.get("severity", 0.5))
    except (TypeError, ValueError):
        severity = 0.5
    severity = max(0.0, min(1.0, severity))
    if severity < min_severity:
        return None

    return {
        "page_a": page_a,
        "page_b": page_b,
        "claim_a": claim_a,
        "claim_b": claim_b,
        "explanation": str(conflict.get("explanation") or "").strip(),
        "resolution_hint": str(conflict.get("resolution_hint") or "").strip(),
        "severity": severity,
        "conflict_type": str(conflict.get("conflict_type") or "unspecified").strip(),
    }


def _fingerprint(c: dict) -> str:
    """Stable ID for the seen ledger so re-runs don't re-file the same conflict.

    Order-insensitive: swapping page_a and page_b yields the same fingerprint.
    """
    pages = sorted([c["page_a"], c["page_b"]])
    claims = sorted([c["claim_a"][:120], c["claim_b"][:120]])
    return hash8("|".join(pages + claims))


# ---------------------------------------------------------------------------
# Candidate writer
# ---------------------------------------------------------------------------

def _build_contradiction_page(
    c: dict, *, domain: str, candidate_id: str, target_path: str
) -> str:
    title = f"Conflict: {c['page_a']} vs {c['page_b']}"
    now = now_iso()
    fm = {
        "title": title,
        "domain": domain,
        "type": "contradiction-note",
        "status": "candidate",
        "confidence": round(c["severity"], 2),
        "sources": [],
        "created_at": now,
        "updated_at": now,
        "generated_by": "conflicAgent",
        "tags": ["conflict", "contradiction"],
        "candidate_id": candidate_id,
        "candidate_operation": "create",
        "target_path": target_path,
        "raw_ids": [],
    }
    fm_yaml = yaml.dump(fm, sort_keys=False, allow_unicode=True).strip()

    body = [
        f"# {title}",
        "",
        "## Conflict Type",
        c["conflict_type"] or "unspecified",
        "",
        "## Claim A",
        f"> [[{c['page_a']}]]",
        "",
        c["claim_a"],
        "",
        "## Claim B",
        f"> [[{c['page_b']}]]",
        "",
        c["claim_b"],
        "",
        "## Why These Conflict",
        c["explanation"] or "(no explanation supplied)",
        "",
        "## Suggested Resolution",
        c["resolution_hint"] or "(none — needs human judgement)",
        "",
        f"**Severity:** {c['severity']:.2f}",
        "",
        "## Status",
        "> [!contradiction]",
        f"> **Conflict:** {c['page_a']} says one thing; {c['page_b']} says another.",
        f"> **Possible explanation:** {c['explanation'] or 'see body'}",
        f"> **Confidence:** {c['severity']:.2f}",
        "> **Status:** unresolved",
        "",
    ]

    return f"---\n{fm_yaml}\n---\n\n" + "\n".join(body)


def _write_candidate_page(
    *, repo_root: Path, domain: str, filename: str, content: str
) -> str:
    """Write to candidates/<domain>/pending/<filename>. Returns the filename."""
    out_dir = repo_root / "candidates" / domain / "pending"
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(out_dir / filename, content)
    return filename


# ---------------------------------------------------------------------------
# Prompt + context helpers
# ---------------------------------------------------------------------------

def _substitute(template: str, **values: str) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


def _render_context_block(pages) -> str:
    if not pages:
        return "(no wiki pages available — the domain may be empty)"
    blocks: list[str] = []
    for p in pages:
        label = "APPROVED" if p.status == "approved" else "CANDIDATE"
        blocks.append(
            f"### [{label}] {p.title}  path=`{p.path}`  confidence={p.confidence:.2f}\n"
            f"{p.body}\n\n---"
        )
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run_conflic_agent(
    *,
    meta: "AgentMeta",
    repo_root: Path,
    job_id: str,
    question_override: Optional[str] = None,
    work_scope: str = "all",
    seen: Optional["SeenTracker"] = None,
    **_ignored,
) -> dict:
    """Execute one conflicAgent run. Returns {message, outputs, ...}."""
    domain = str(meta.config.get("domain") or "").strip()
    if not domain:
        raise ValueError("conflicAgent requires `domain` in config.yaml.")

    model = str(meta.config.get("model") or "claude-sonnet-4-6")
    max_tokens = int(meta.config.get("max_tokens", 4096))
    max_pages = int(meta.config.get("max_pages", 24))
    max_chars = int(meta.config.get("max_context_chars", 80_000))
    max_conflicts = int(meta.config.get("max_conflicts_per_run", 10))
    min_severity = float(meta.config.get("min_severity", 0.35))
    include_candidates = bool(meta.config.get("include_candidates", True))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set — conflicAgent cannot call Claude."
        )

    if not meta.prompt.strip():
        raise RuntimeError("prompt.md is empty — agent cannot run without a prompt template.")

    focus = (question_override or meta.config.get("focus") or "").strip()

    pages = collect_ask_context(
        question=focus or f"conflicting facts and contradictions in {domain}",
        domain=domain,
        repo_root=repo_root,
        include_candidates=include_candidates,
        max_pages=max_pages,
        max_chars=max_chars,
    )

    prompt = _substitute(
        meta.prompt,
        domain=domain,
        now=now_iso(),
        max_conflicts=str(max_conflicts),
        focus=focus or "(none — survey the whole domain)",
    )
    user_msg = (
        f"{prompt}\n\n"
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
        raise RuntimeError(
            f"Claude API error: {exc}\n\n{traceback.format_exc(limit=3)}"
        ) from exc

    text = (message.content[0].text or "").strip()
    if not text:
        raise RuntimeError("Claude returned empty content.")

    raw_conflicts = _parse_conflicts(text)
    normalized = [
        n for n in (_normalize(c, min_severity) for c in raw_conflicts) if n
    ]

    # Dedup via the seen ledger — always applied, not just under work_scope=new.
    # conflicAgent is manual-only; the ledger prevents the same page-pair
    # claim-pair from producing a duplicate candidate if you re-run on the
    # same wiki state.
    fresh: list[dict] = []
    new_fingerprints: list[str] = []
    for c in normalized:
        fp = _fingerprint(c)
        if seen is not None and fp in seen.initial:
            continue
        if fp in new_fingerprints:
            continue
        fresh.append(c)
        new_fingerprints.append(fp)
        if len(fresh) >= max_conflicts:
            break

    usage = getattr(message, "usage", None)
    tokens_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    tokens_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

    if not fresh:
        msg = (
            f"No new conflicts — LLM returned {len(raw_conflicts)}, "
            f"{len(raw_conflicts) - len(normalized)} below severity threshold, "
            f"{len(normalized) - len(fresh)} already seen. "
            f"(tokens {tokens_in}→{tokens_out})"
        )
        return {
            "message": msg,
            "outputs": [],
            "domain": domain,
            "work_scope": work_scope,
            "skipped": True,
            "conflicts_returned": len(raw_conflicts),
            "conflicts_new": 0,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    written: list[str] = []
    for c, fp in zip(fresh, new_fingerprints):
        short_title = f"{c['page_a']} vs {c['page_b']}"
        candidate_id = build_candidate_id(
            f"conflict {slug_from_title(short_title)[:40]}",
            f"{c['claim_a']}|{c['claim_b']}",
        )
        slug = slug_from_title(short_title)[:60] or "conflict"
        filename = f"{candidate_id}.md"
        target_path = (
            f"domains/{domain}/reports/contradictions/{slug}-{fp}.md"
        )
        page_text = _build_contradiction_page(
            c, domain=domain, candidate_id=candidate_id, target_path=target_path
        )
        _write_candidate_page(
            repo_root=repo_root, domain=domain,
            filename=filename, content=page_text,
        )
        written.append(f"candidates/{domain}/pending/{filename}")
        if seen is not None:
            seen.mark(fp)

    append_domain_log(
        repo_root, domain, "conflict-scan",
        f"{len(written)} conflict candidate(s) filed for review "
        f"({len(raw_conflicts)} returned, threshold={min_severity:.2f})",
    )

    return {
        "message": (
            f"Filed {len(written)} conflict candidate(s) → "
            f"candidates/{domain}/pending/ "
            f"(returned={len(raw_conflicts)}, threshold={min_severity:.2f}, "
            f"tokens {tokens_in}→{tokens_out})"
        ),
        "outputs": written,
        "domain": domain,
        "work_scope": work_scope,
        "conflicts_returned": len(raw_conflicts),
        "conflicts_new": len(written),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }
