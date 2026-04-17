import pytest
from pathlib import Path
from src.query import search_pages, PageMatch, confidence_label

APPROVED_PAGE = """\
---
title: "NNAPI Delegate"
domain: edge-ai
type: concept
status: approved
confidence: 0.82
sources: []
created_at: "2026-04-16T12:00:00+00:00"
updated_at: "2026-04-16T12:00:00+00:00"
tags:
  - nnapi
  - delegate
---

# NNAPI Delegate

## Summary
NNAPI is Android's Neural Networks API. It allows apps to offload computation to hardware accelerators.
"""

CANDIDATE_PAGE = """\
---
title: "NNAPI Fallback Modes"
domain: edge-ai
type: concept
status: candidate
confidence: 0.60
sources: []
created_at: "2026-04-16T13:00:00+00:00"
updated_at: "2026-04-16T13:00:00+00:00"
tags:
  - nnapi
  - fallback
candidate_id: cand_test
candidate_operation: create
target_path: domains/edge-ai/concepts/nnapi-fallback-modes.md
raw_ids: []
---

# NNAPI Fallback Modes

## Summary
When NNAPI acceleration is not available, the TFLite runtime falls back to CPU.
"""


def _setup_wiki(repo_root: Path):
    (repo_root / "domains" / "edge-ai" / "concepts").mkdir(parents=True)
    (repo_root / "candidates" / "edge-ai" / "pending").mkdir(parents=True)
    (repo_root / "domains" / "edge-ai" / "concepts" / "nnapi-delegate.md").write_text(APPROVED_PAGE)
    (repo_root / "candidates" / "edge-ai" / "pending" / "cand_nnapi-fallback.md").write_text(CANDIDATE_PAGE)


def test_search_finds_approved(repo_root):
    _setup_wiki(repo_root)
    results = search_pages("NNAPI", "edge-ai", repo_root=repo_root)
    titles = [r.title for r in results]
    assert "NNAPI Delegate" in titles


def test_search_finds_candidate(repo_root):
    _setup_wiki(repo_root)
    results = search_pages("fallback", "edge-ai", repo_root=repo_root)
    titles = [r.title for r in results]
    assert "NNAPI Fallback Modes" in titles


def test_search_result_has_status_badge(repo_root):
    _setup_wiki(repo_root)
    results = search_pages("NNAPI", "edge-ai", repo_root=repo_root)
    for r in results:
        assert r.status in ("approved", "candidate", "rejected", "archived", "superseded")


def test_search_result_has_confidence(repo_root):
    _setup_wiki(repo_root)
    results = search_pages("NNAPI", "edge-ai", repo_root=repo_root)
    for r in results:
        assert 0.0 <= r.confidence <= 1.0


def test_search_empty_query_returns_all(repo_root):
    _setup_wiki(repo_root)
    results = search_pages("", "edge-ai", repo_root=repo_root)
    assert len(results) >= 2


def test_search_no_results(repo_root):
    _setup_wiki(repo_root)
    results = search_pages("quantum computing", "edge-ai", repo_root=repo_root)
    assert results == []


def test_search_ranks_title_match_above_body_match(repo_root):
    _setup_wiki(repo_root)
    # "fallback" appears in one title and one body — the title match should lead.
    results = search_pages("fallback", "edge-ai", repo_root=repo_root)
    assert results
    assert results[0].title == "NNAPI Fallback Modes"


def test_search_multi_word_query_scores_both(repo_root):
    _setup_wiki(repo_root)
    results = search_pages("NNAPI fallback", "edge-ai", repo_root=repo_root)
    titles = [r.title for r in results]
    assert "NNAPI Fallback Modes" in titles
    # Page that has both terms should rank above page with just one.
    assert results[0].title == "NNAPI Fallback Modes"


def test_confidence_label():
    assert confidence_label(0.95) == "Very high"
    assert confidence_label(0.80) == "High"
    assert confidence_label(0.65) == "Medium"
    assert confidence_label(0.45) == "Low"
    assert confidence_label(0.20) == "Very low"


# ---------------------------------------------------------------------------
# Filter tests (new kwargs on search_pages)
# ---------------------------------------------------------------------------

ENTITY_PAGE = """\
---
title: "Hailo-8 Chip"
domain: edge-ai
type: entity
status: approved
confidence: 0.55
sources: []
created_at: "2026-04-16T14:00:00+00:00"
updated_at: "2026-04-16T14:00:00+00:00"
tags:
  - hardware
  - hailo
---

# Hailo-8 Chip

Runs INT8 inference at the edge.
"""


def _setup_wiki_with_entity(repo_root: Path):
    _setup_wiki(repo_root)
    (repo_root / "domains" / "edge-ai" / "entities").mkdir(parents=True)
    (repo_root / "domains" / "edge-ai" / "entities" / "hailo-8.md").write_text(ENTITY_PAGE)


def test_search_filter_by_type(repo_root):
    _setup_wiki_with_entity(repo_root)
    results = search_pages("", "edge-ai", repo_root=repo_root, types=["concept"])
    assert all(r.type == "concept" for r in results)
    assert {r.title for r in results} == {"NNAPI Delegate", "NNAPI Fallback Modes"}


def test_search_filter_by_tag(repo_root):
    _setup_wiki_with_entity(repo_root)
    results = search_pages("", "edge-ai", repo_root=repo_root, tags=["hailo"])
    assert [r.title for r in results] == ["Hailo-8 Chip"]


def test_search_filter_by_status_approved_only(repo_root):
    _setup_wiki_with_entity(repo_root)
    results = search_pages("nnapi", "edge-ai", repo_root=repo_root, statuses=["approved"])
    assert all(r.status == "approved" for r in results)
    assert "NNAPI Fallback Modes" not in [r.title for r in results]


def test_search_filter_by_min_confidence(repo_root):
    _setup_wiki_with_entity(repo_root)
    results = search_pages("", "edge-ai", repo_root=repo_root, min_confidence=0.70)
    assert all(r.confidence >= 0.70 for r in results)
    # Hailo (0.55) and Fallback (0.60) filtered out; only NNAPI Delegate (0.82).
    assert [r.title for r in results] == ["NNAPI Delegate"]


def test_search_filters_compose(repo_root):
    _setup_wiki_with_entity(repo_root)
    results = search_pages(
        "",
        "edge-ai",
        repo_root=repo_root,
        types=["concept"],
        statuses=["approved"],
        min_confidence=0.5,
    )
    assert [r.title for r in results] == ["NNAPI Delegate"]


# ---------------------------------------------------------------------------
# Ask primitives (no network)
# ---------------------------------------------------------------------------

from src.query import (
    ASK_SECTIONS,
    AskResult,
    ask_llm,
    build_ask_prompt,
    collect_ask_context,
    parse_ask_response,
)


def test_collect_ask_context_defaults_to_approved_only(repo_root):
    _setup_wiki(repo_root)
    pages = collect_ask_context("nnapi", "edge-ai", repo_root, include_candidates=False)
    statuses = {p.status for p in pages}
    assert statuses == {"approved"}
    assert all(p.body for p in pages)


def test_collect_ask_context_include_candidates_when_opted_in(repo_root):
    _setup_wiki(repo_root)
    pages = collect_ask_context("nnapi", "edge-ai", repo_root, include_candidates=True)
    statuses = {p.status for p in pages}
    assert "candidate" in statuses


def test_collect_ask_context_respects_max_chars(repo_root):
    _setup_wiki(repo_root)
    # Tight budget: we expect exactly one page (the first has priority).
    pages = collect_ask_context(
        "nnapi", "edge-ai", repo_root,
        include_candidates=True,
        max_pages=10,
        max_chars=50,
    )
    assert len(pages) == 1


def test_collect_ask_context_respects_max_pages(repo_root):
    _setup_wiki(repo_root)
    pages = collect_ask_context(
        "nnapi", "edge-ai", repo_root,
        include_candidates=True,
        max_pages=1,
    )
    assert len(pages) == 1


def test_build_ask_prompt_marks_approved_and_candidate(repo_root):
    _setup_wiki(repo_root)
    pages = collect_ask_context("nnapi", "edge-ai", repo_root, include_candidates=True)
    prompt = build_ask_prompt("What is NNAPI?", "edge-ai", pages, repo_root)
    assert "[APPROVED]" in prompt
    assert "[CANDIDATE]" in prompt
    assert "## Answer" in prompt
    assert "## Candidate Additions" in prompt
    assert "## Conflicts / Uncertainty" in prompt
    assert "## Suggested Next Actions" in prompt
    assert "What is NNAPI?" in prompt
    assert "edge-ai" in prompt


def test_build_ask_prompt_empty_pool(repo_root):
    prompt = build_ask_prompt("q", "edge-ai", [], repo_root)
    assert "(no wiki pages matched)" in prompt


def test_parse_ask_response_all_four_sections():
    text = """\
## Answer
The answer is 42 [APPROVED] `domains/edge-ai/concepts/nnapi-delegate.md`.

## Candidate Additions
None

## Conflicts / Uncertainty
None

## Suggested Next Actions
- Ingest datasheet
"""
    parsed = parse_ask_response(text)
    assert parsed["Answer"].startswith("The answer is 42")
    assert parsed["Candidate Additions"] == "None"
    assert parsed["Conflicts / Uncertainty"] == "None"
    assert "Ingest datasheet" in parsed["Suggested Next Actions"]


def test_parse_ask_response_missing_sections_become_none():
    text = """\
## Answer
Short answer.
"""
    parsed = parse_ask_response(text)
    assert parsed["Answer"] == "Short answer."
    assert parsed["Candidate Additions"] == "None"
    assert parsed["Conflicts / Uncertainty"] == "None"
    assert parsed["Suggested Next Actions"] == "None"


def test_parse_ask_response_handles_heading_aliases():
    text = """\
## Answer
Body.

## Conflicts
A conflict.

## Next Actions
Take step X.
"""
    parsed = parse_ask_response(text)
    assert parsed["Conflicts / Uncertainty"] == "A conflict."
    assert parsed["Suggested Next Actions"] == "Take step X."


def test_ask_llm_empty_question_returns_error(repo_root):
    _setup_wiki(repo_root)
    result = ask_llm("   ", "edge-ai", repo_root=repo_root)
    assert isinstance(result, AskResult)
    assert result.error and "Empty question" in result.error
    assert result.tokens_in == 0


def test_ask_llm_missing_api_key(monkeypatch, repo_root):
    _setup_wiki(repo_root)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = ask_llm("What is NNAPI?", "edge-ai", repo_root=repo_root, api_key=None)
    assert result.error and "ANTHROPIC_API_KEY" in result.error
    assert result.cited_pages, "cited pages should still be populated for transparency"
    assert result.scope == "approved"
