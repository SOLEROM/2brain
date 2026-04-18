"""Search and LLM-powered Ask primitives for the Query tab.

Two surfaces:

- `search_pages(...)`    — keyword / substring ranking, with optional filters
                           (types, tags, statuses, min_confidence).
- `ask_llm(...)`         — Claude-backed Q&A grounded in the wiki pages. Returns
                           an `AskResult` with the raw Markdown answer, cited
                           pages, and usage info. Errors are captured rather
                           than raised.
"""
from __future__ import annotations

import os
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import anthropic

from src.config import load_agents_config
from src.utils import now_iso
from src.validate import parse_frontmatter


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PageMatch:
    title: str
    path: str
    status: str
    confidence: float
    domain: str
    type: str
    tags: list[str] = field(default_factory=list)
    snippet: str = ""
    score: float = 0.0
    # Full page body. Populated when the caller explicitly needs it (e.g. the
    # Ask pipeline). `search_pages` leaves it empty because results only need
    # the snippet for rendering.
    body: str = ""


@dataclass
class AskResult:
    question: str
    answer_md: str
    sections: dict
    cited_pages: list[PageMatch]
    model: str
    tokens_in: int
    tokens_out: int
    duration_s: float
    scope: str  # "approved" or "approved+candidates"
    error: Optional[str] = None
    # Effective settings used for this request (echoed to the UI).
    style: str = "balanced"
    temperature: float = 0.3
    max_tokens: int = 2048


# ---------------------------------------------------------------------------
# Confidence label
# ---------------------------------------------------------------------------

def confidence_label(score: float) -> str:
    if score >= 0.90:
        return "Very high"
    if score >= 0.75:
        return "High"
    if score >= 0.55:
        return "Medium"
    if score >= 0.35:
        return "Low"
    return "Very low"


# ---------------------------------------------------------------------------
# Page loading (shared by search + ask)
# ---------------------------------------------------------------------------

def _load_pages(
    domain: str,
    repo_root: Path,
    include_candidates: bool,
) -> list[tuple[Path, dict, str]]:
    pages: list[tuple[Path, dict, str]] = []
    dirs = [repo_root / "domains" / domain]
    if include_candidates:
        dirs.append(repo_root / "candidates" / domain / "pending")
    for search_dir in dirs:
        if not search_dir.exists():
            continue
        for md_file in search_dir.rglob("*.md"):
            if md_file.name in ("index.md", "log.md", "schema.md"):
                continue
            if "indexes" in md_file.parts:
                continue
            fm, body = parse_frontmatter(md_file)
            if fm.get("title"):
                pages.append((md_file, fm, body))
    return pages


def _normalize_filter(val: Optional[Iterable[str]]) -> Optional[set[str]]:
    if val is None:
        return None
    cleaned = {str(x).strip().lower() for x in val if str(x).strip()}
    return cleaned or None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_pages(
    query: str,
    domain: str,
    repo_root: Path = Path("."),
    include_candidates: bool = True,
    *,
    types: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
    statuses: Optional[Iterable[str]] = None,
    min_confidence: Optional[float] = None,
) -> list[PageMatch]:
    """Search approved and candidate pages. Optional filters refine the set.

    Filters use OR within a dimension and AND across dimensions.
    """
    pages = _load_pages(domain, repo_root, include_candidates)
    query_lower = (query or "").lower().strip()
    words = query_lower.split()

    type_set = _normalize_filter(types)
    tag_set = _normalize_filter(tags)
    status_set = _normalize_filter(statuses)
    min_conf = float(min_confidence) if min_confidence is not None else None

    results: list[PageMatch] = []
    for path, fm, body in pages:
        status = fm.get("status", "unknown")
        if status == "candidate" and not include_candidates:
            continue
        if status not in ("approved", "candidate"):
            continue

        if status_set and status.lower() not in status_set:
            continue

        page_type = str(fm.get("type", "unknown"))
        if type_set and page_type.lower() not in type_set:
            continue

        page_tags = [str(t) for t in (fm.get("tags") or [])]
        if tag_set:
            page_tag_set = {t.lower() for t in page_tags}
            if page_tag_set.isdisjoint(tag_set):
                continue

        confidence = float(fm.get("confidence", 0.0) or 0.0)
        if min_conf is not None and confidence < min_conf:
            continue

        title = fm.get("title", "")
        score = _score(query_lower, words, title, page_tags, body)
        if words and score == 0:
            continue

        results.append(PageMatch(
            title=title,
            path=str(path),
            status=status,
            confidence=confidence,
            domain=fm.get("domain", domain),
            type=page_type,
            tags=page_tags,
            snippet=_extract_snippet(body, words),
            score=score,
        ))

    # Rank: search score (primary) > approved beats candidate > higher confidence.
    results.sort(
        key=lambda r: (r.score, r.status == "approved", r.confidence),
        reverse=True,
    )
    return results


def _score(query: str, words: list[str], title: str, tags: list[str], body: str) -> float:
    if not words:
        return 1.0
    title_lc = title.lower()
    tags_lc = " ".join(tags).lower()
    body_lc = body.lower()

    score = 0.0
    for w in words:
        if w in title_lc:
            score += 3.0
        if w in tags_lc:
            score += 2.0
        score += body_lc.count(w) * 0.5

    if query and query in body_lc:
        score += 2.0
    if query and query in title_lc:
        score += 5.0
    return score


def _extract_snippet(body: str, words: list[str], context: int = 120) -> str:
    if not body:
        return ""
    if not words:
        return body[:240].strip()
    body_lc = body.lower()
    best_idx = -1
    for w in words:
        idx = body_lc.find(w)
        if idx != -1 and (best_idx == -1 or idx < best_idx):
            best_idx = idx
    if best_idx == -1:
        return body[:240].strip()
    start = max(0, best_idx - context)
    end = min(len(body), best_idx + context)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(body) else ""
    return (prefix + body[start:end].strip() + suffix).replace("\n", " ")


# ---------------------------------------------------------------------------
# Ask: context collection
# ---------------------------------------------------------------------------

def collect_ask_context(
    question: str,
    domain: str,
    repo_root: Path,
    include_candidates: bool = False,
    max_pages: int = 12,
    max_chars: int = 40_000,
) -> list[PageMatch]:
    """Rank pages against the question and greedily pack under `max_chars`.

    When `include_candidates=False` (default, per CLAUDE.md guidance that the
    LLM grounds in approved knowledge), candidate pages are excluded from the
    pool *before* ranking so they can't push approved pages out of the budget.

    Each returned `PageMatch` carries its full `body` so the caller can
    embed it in the prompt.
    """
    pages = _load_pages(domain, repo_root, include_candidates=True)
    q_lower = (question or "").lower().strip()
    words = q_lower.split()

    scored: list[PageMatch] = []
    for path, fm, body in pages:
        status = fm.get("status", "unknown")
        if status not in ("approved", "candidate"):
            continue
        if not include_candidates and status != "approved":
            continue

        title = fm.get("title", "")
        tags = [str(t) for t in (fm.get("tags") or [])]
        s = _score(q_lower, words, title, tags, body)
        # When the user doesn't type a query, _score returns 1.0 for all pages;
        # still allow fallback to top-N by confidence.
        scored.append(PageMatch(
            title=title,
            path=str(path),
            status=status,
            confidence=float(fm.get("confidence", 0.0) or 0.0),
            domain=fm.get("domain", domain),
            type=str(fm.get("type", "unknown")),
            tags=tags,
            snippet=_extract_snippet(body, words),
            score=s,
            body=body,
        ))

    scored.sort(
        key=lambda r: (r.score, r.status == "approved", r.confidence),
        reverse=True,
    )

    picked: list[PageMatch] = []
    remaining = max_chars
    for m in scored:
        if len(picked) >= max_pages:
            break
        # Account for body + a small header overhead per page.
        cost = len(m.body) + 200
        if cost > remaining and picked:
            break
        picked.append(m)
        remaining -= cost
    return picked


# ---------------------------------------------------------------------------
# Ask: prompt + parsing
# ---------------------------------------------------------------------------

ASK_SECTIONS = ("Answer", "Candidate Additions", "Conflicts / Uncertainty", "Suggested Next Actions")


# Style presets shown in the Ask UI. Keep this map in sync with ask.html.
ASK_STYLES: dict[str, str] = {
    "concise": (
        "Keep responses terse. Prefer short bullets over paragraphs. "
        "Aim for ≤8 bullets per section where possible. Cut prose to the minimum required to be complete."
    ),
    "balanced": (
        "Moderate verbosity. Give enough context to act on the answer, "
        "but avoid padding. Evidence > prose."
    ),
    "informative": (
        "Favour depth. Explain mechanisms, trade-offs, and caveats where they aid understanding. "
        "Every claim still requires a citation — no speculation."
    ),
}
ASK_STYLE_DEFAULT = "balanced"


# Anthropic models the Ask UI may select. Any other value falls back to the
# `query_agent.model` configured in `config/agents.yaml`.
ASK_ALLOWED_MODELS: set[str] = {
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
}


def _rel_path_for_prompt(abs_path: str, repo_root: Path) -> str:
    try:
        return str(Path(abs_path).resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return abs_path


def build_ask_prompt(
    question: str,
    domain: str,
    pages: list[PageMatch],
    repo_root: Path,
    now_iso_str: Optional[str] = None,
    style: str = ASK_STYLE_DEFAULT,
) -> str:
    """Compose the Ask prompt per CLAUDE.md §Agent Operations → Query.

    ``style`` selects one of ``ASK_STYLES`` — unknown values fall back to the
    default.
    """
    ts = now_iso_str or now_iso()
    style_directive = ASK_STYLES.get(style, ASK_STYLES[ASK_STYLE_DEFAULT])

    blocks: list[str] = []
    for m in pages:
        label = "APPROVED" if m.status == "approved" else "CANDIDATE"
        rel = _rel_path_for_prompt(m.path, repo_root)
        blocks.append(
            f"### [{label}] {m.title}  path=`{rel}`  confidence={m.confidence:.2f}\n"
            f"{m.body}\n\n---"
        )
    pages_block = "\n\n".join(blocks) if blocks else "(no wiki pages matched)"

    return f"""You are the 2brain Query Agent. Answer the user's question using ONLY the wiki pages provided below. Treat [APPROVED] pages as ground truth. Treat [CANDIDATE] pages as provisional and LABEL them as such in every citation. If the wiki does not cover the question, say so — do not invent facts.

Output STRICT Markdown with exactly these four sections in this order:

## Answer
## Candidate Additions
## Conflicts / Uncertainty
## Suggested Next Actions

Rules:
- Cite every non-trivial claim. Citation format: [APPROVED] `target/path.md` or [CANDIDATE] `target/path.md` (inline, right after the claim).
- If a section has nothing to report, write the single word "None".
- Never invent page titles, URLs, or raw_ids.

## Style directive
{style_directive}

## Domain
{domain}

## Question
{question}

## Wiki pages (ranked by relevance)

{pages_block}

Current timestamp: {ts}
"""


def parse_ask_response(text: str) -> dict:
    """Split the Markdown reply on the four known section headers.

    Missing sections default to "None" so the template can render consistently.
    Tolerant to extra preamble or trailing text.
    """
    sections = {name: "None" for name in ASK_SECTIONS}
    if not text:
        return sections

    # Tokenise by line so we can walk section boundaries.
    lines = text.splitlines()
    current: Optional[str] = None
    buffers: dict[str, list[str]] = {name: [] for name in ASK_SECTIONS}

    def _match_heading(line: str) -> Optional[str]:
        stripped = line.strip()
        if not stripped.startswith("## "):
            return None
        heading = stripped[3:].strip().lower()
        for name in ASK_SECTIONS:
            if heading == name.lower():
                return name
        # Accept common variants.
        aliases = {
            "conflicts": "Conflicts / Uncertainty",
            "conflicts and uncertainty": "Conflicts / Uncertainty",
            "uncertainty": "Conflicts / Uncertainty",
            "next actions": "Suggested Next Actions",
            "suggested actions": "Suggested Next Actions",
        }
        return aliases.get(heading)

    for line in lines:
        match = _match_heading(line)
        if match is not None:
            current = match
            continue
        if current is None:
            continue
        buffers[current].append(line)

    for name in ASK_SECTIONS:
        body = "\n".join(buffers[name]).strip()
        if body:
            sections[name] = body
    return sections


# ---------------------------------------------------------------------------
# Ask: main entrypoint
# ---------------------------------------------------------------------------

def _load_query_agent_cfg(repo_root: Path) -> dict:
    path = repo_root / "config" / "agents.yaml"
    cfg = load_agents_config(path) if path.exists() else load_agents_config()
    q = (cfg or {}).get("query_agent") or {}
    return {
        "model": q.get("model", "claude-sonnet-4-6"),
        "max_context_chars": int(q.get("max_context_chars", 40_000)),
        "max_pages": int(q.get("max_pages", 12)),
        "max_tokens": int(q.get("max_tokens", 2048)),
        "include_candidates_default": bool(q.get("include_candidates_default", False)),
    }


# Temperature / max_tokens guardrails — matches the UI sliders/selects.
_ASK_TEMP_MIN = 0.0
_ASK_TEMP_MAX = 1.0
_ASK_MAX_TOKENS_MIN = 256
_ASK_MAX_TOKENS_MAX = 8192


def _resolve_ask_overrides(
    cfg: dict,
    style: Optional[str],
    temperature: Optional[float],
    max_tokens: Optional[int],
    model: Optional[str],
) -> dict:
    """Clamp/allowlist per-request UI overrides, falling back to config defaults."""
    effective_style = style if style in ASK_STYLES else ASK_STYLE_DEFAULT

    if temperature is None:
        effective_temp = 0.3
    else:
        try:
            effective_temp = max(_ASK_TEMP_MIN, min(_ASK_TEMP_MAX, float(temperature)))
        except (TypeError, ValueError):
            effective_temp = 0.3

    if max_tokens is None:
        effective_max_tokens = int(cfg["max_tokens"])
    else:
        try:
            effective_max_tokens = max(
                _ASK_MAX_TOKENS_MIN,
                min(_ASK_MAX_TOKENS_MAX, int(max_tokens)),
            )
        except (TypeError, ValueError):
            effective_max_tokens = int(cfg["max_tokens"])

    effective_model = (
        model if (model and model in ASK_ALLOWED_MODELS) else cfg["model"]
    )
    return {
        "style": effective_style,
        "temperature": effective_temp,
        "max_tokens": effective_max_tokens,
        "model": effective_model,
    }


def ask_llm(
    question: str,
    domain: str,
    repo_root: Path = Path("."),
    include_candidates: bool = False,
    api_key: Optional[str] = None,
    style: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> AskResult:
    """Run the Ask agent. Never raises — errors are returned on AskResult.

    ``style`` / ``temperature`` / ``max_tokens`` / ``model`` are optional UI
    overrides. Invalid values silently fall back to safe defaults.
    """
    started = time.monotonic()
    scope = "approved+candidates" if include_candidates else "approved"

    try:
        cfg = _load_query_agent_cfg(repo_root)
    except Exception as exc:
        return AskResult(
            question=question, answer_md="", sections={n: "None" for n in ASK_SECTIONS},
            cited_pages=[], model="?", tokens_in=0, tokens_out=0,
            duration_s=time.monotonic() - started, scope=scope,
            error=f"Failed to load agents.yaml: {exc}",
        )

    ov = _resolve_ask_overrides(cfg, style, temperature, max_tokens, model)

    if not (question or "").strip():
        return AskResult(
            question=question, answer_md="", sections={n: "None" for n in ASK_SECTIONS},
            cited_pages=[], model=ov["model"], tokens_in=0, tokens_out=0,
            duration_s=time.monotonic() - started, scope=scope,
            error="Empty question — type something to ask.",
            style=ov["style"], temperature=ov["temperature"], max_tokens=ov["max_tokens"],
        )

    pages = collect_ask_context(
        question=question,
        domain=domain,
        repo_root=repo_root,
        include_candidates=include_candidates,
        max_pages=cfg["max_pages"],
        max_chars=cfg["max_context_chars"],
    )

    effective_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not effective_key:
        return AskResult(
            question=question, answer_md="", sections={n: "None" for n in ASK_SECTIONS},
            cited_pages=pages, model=ov["model"], tokens_in=0, tokens_out=0,
            duration_s=time.monotonic() - started, scope=scope,
            error="ANTHROPIC_API_KEY is not set — Ask cannot call Claude.",
            style=ov["style"], temperature=ov["temperature"], max_tokens=ov["max_tokens"],
        )

    prompt = build_ask_prompt(question, domain, pages, repo_root, style=ov["style"])

    try:
        client = anthropic.Anthropic(api_key=effective_key)
        message = client.messages.create(
            model=ov["model"],
            max_tokens=ov["max_tokens"],
            temperature=ov["temperature"],
            messages=[{"role": "user", "content": prompt}],
        )
        text = (message.content[0].text or "").strip()
        usage = getattr(message, "usage", None)
        tok_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        tok_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    except Exception as exc:
        return AskResult(
            question=question, answer_md="", sections={n: "None" for n in ASK_SECTIONS},
            cited_pages=pages, model=ov["model"], tokens_in=0, tokens_out=0,
            duration_s=time.monotonic() - started, scope=scope,
            error=f"Claude API error: {exc}\n\n{traceback.format_exc(limit=3)}",
            style=ov["style"], temperature=ov["temperature"], max_tokens=ov["max_tokens"],
        )

    sections = parse_ask_response(text)
    return AskResult(
        question=question,
        answer_md=text,
        sections=sections,
        cited_pages=pages,
        model=ov["model"],
        tokens_in=tok_in,
        tokens_out=tok_out,
        duration_s=time.monotonic() - started,
        scope=scope,
        error=None,
        style=ov["style"],
        temperature=ov["temperature"],
        max_tokens=ov["max_tokens"],
    )
