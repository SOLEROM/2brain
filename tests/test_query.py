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


def test_confidence_label():
    assert confidence_label(0.95) == "Very high"
    assert confidence_label(0.80) == "High"
    assert confidence_label(0.65) == "Medium"
    assert confidence_label(0.45) == "Low"
    assert confidence_label(0.20) == "Very low"
