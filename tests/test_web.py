import pytest
from fastapi.testclient import TestClient
from pathlib import Path

CANDIDATE_PAGE = """\
---
title: "Test Candidate"
domain: edge-ai
type: concept
status: candidate
confidence: 0.75
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags:
  - test
candidate_id: cand_20260416_153000_test-candidate_a1b2c3d4
candidate_operation: create
target_path: domains/edge-ai/concepts/test-candidate.md
raw_ids: []
---

# Test Candidate

## Summary
Test content here.
"""


@pytest.fixture
def wiki_root(tmp_path):
    for d in ["domains/edge-ai/concepts", "domains/edge-ai/indexes",
              "candidates/edge-ai/pending", "candidates/edge-ai/rejected",
              "candidates/edge-ai/archived", "audit", "jobs/completed"]:
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "domains/edge-ai/log.md").write_text("# Log\n")
    (tmp_path / "domains/edge-ai/index.md").write_text("# Index\n")
    (tmp_path / "candidates/edge-ai/pending/cand_test.md").write_text(CANDIDATE_PAGE)
    return tmp_path


@pytest.fixture
def client(wiki_root):
    from src.web.app import create_app
    app = create_app(repo_root=wiki_root)
    return TestClient(app)


def test_candidates_list_page(client):
    resp = client.get("/candidates/edge-ai")
    assert resp.status_code == 200
    assert "Test Candidate" in resp.text


def test_candidate_review_page(client):
    resp = client.get("/candidates/edge-ai/cand_test.md")
    assert resp.status_code == 200
    assert "Test Candidate" in resp.text
    assert "0.75" in resp.text


def test_approve_candidate(client, wiki_root):
    resp = client.post("/candidates/edge-ai/cand_test.md/approve",
                       data={"reviewed_by": "vlad"},
                       follow_redirects=False)
    assert resp.status_code in (200, 302, 303)
    target = wiki_root / "domains" / "edge-ai" / "concepts" / "test-candidate.md"
    assert target.exists()


def test_reject_candidate(client, wiki_root):
    resp = client.post("/candidates/edge-ai/cand_test.md/reject",
                       follow_redirects=False)
    assert resp.status_code in (200, 302, 303)
    rejected = wiki_root / "candidates" / "edge-ai" / "rejected" / "cand_test.md"
    assert rejected.exists()


def test_wiki_browse_page(client):
    resp = client.get("/wiki/edge-ai")
    assert resp.status_code == 200


def test_query_page_loads(client):
    resp = client.get("/query/edge-ai")
    assert resp.status_code == 200


def test_query_returns_results(client):
    resp = client.get("/query/edge-ai?q=test")
    assert resp.status_code == 200
