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
    assert "Test Candidate" in resp.text


def test_candidate_review_404_on_missing(client):
    resp = client.get("/candidates/edge-ai/does-not-exist.md")
    assert resp.status_code == 404


def test_health_page_loads(client):
    resp = client.get("/health/edge-ai")
    assert resp.status_code == 200
    assert "Health" in resp.text


def test_jobs_page_loads(client):
    resp = client.get("/jobs")
    assert resp.status_code == 200


def test_sources_page_loads(client):
    resp = client.get("/sources")
    assert resp.status_code == 200


def test_wiki_page_view(client, wiki_root):
    # Approve a candidate first so we have an approved page.
    client.post("/candidates/edge-ai/cand_test.md/approve",
                data={"reviewed_by": "vlad"},
                follow_redirects=False)
    resp = client.get("/wiki/edge-ai/page/domains/edge-ai/concepts/test-candidate.md")
    assert resp.status_code == 200
    assert "Test Candidate" in resp.text


def _setup_second_domain(wiki_root: Path, name: str = "robotics") -> None:
    for d in [f"domains/{name}/concepts", f"domains/{name}/indexes"]:
        (wiki_root / d).mkdir(parents=True, exist_ok=True)
    (wiki_root / f"domains/{name}/domain.yaml").write_text(f"name: {name}\n")
    (wiki_root / f"domains/{name}/log.md").write_text("# Log\n")
    (wiki_root / f"domains/{name}/index.md").write_text("# Index\n")


def _approve_test_candidate(client) -> None:
    client.post("/candidates/edge-ai/cand_test.md/approve",
                data={"reviewed_by": "vlad"}, follow_redirects=False)


def test_ask_page_renders_shell(client):
    resp = client.get("/ask/edge-ai")
    assert resp.status_code == 200
    assert 'id="ask-chat"' in resp.text
    assert 'id="ask-clear"' in resp.text
    assert 'id="ask-export"' in resp.text


def test_ask_api_rejects_empty_question(client):
    resp = client.post("/ask/edge-ai/api", data={"q": "  "})
    assert resp.status_code == 400


def test_ask_api_returns_json_on_llm_failure(client, wiki_root, monkeypatch):
    # ask_llm fails fast without an API key — we still want a JSON payload
    # (with `error` set) so the chat UI can render it inline.
    resp = client.post("/ask/edge-ai/api", data={"q": "what is nnapi?"})
    assert resp.status_code == 200
    payload = resp.json()
    assert "sections" in payload
    assert "cited" in payload
    # Without an API key configured in tests, ask_llm returns an error string.
    assert payload.get("error") or payload["sections"]


def test_ask_api_accepts_and_echoes_settings(client, wiki_root, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post("/ask/edge-ai/api", data={
        "q": "anything",
        "style": "informative",
        "temperature": "0.8",
        "max_tokens": "4096",
        "model": "claude-opus-4-7",
    })
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["style"] == "informative"
    assert payload["temperature"] == 0.8
    assert payload["max_tokens"] == 4096
    assert payload["model"] == "claude-opus-4-7"


def test_ask_api_clamps_bad_settings(client, wiki_root, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post("/ask/edge-ai/api", data={
        "q": "anything",
        "style": "nonsense",
        "temperature": "9.0",
        "max_tokens": "999999",
        "model": "not-a-real-model",
    })
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["style"] == "balanced"
    assert payload["temperature"] == 1.0
    assert payload["max_tokens"] == 8192
    # Unknown model falls back to the configured default (from agents.yaml).
    assert payload["model"].startswith("claude-")


def test_wiki_move_page_to_another_domain(client, wiki_root):
    _setup_second_domain(wiki_root, "robotics")
    _approve_test_candidate(client)
    src_rel = "domains/edge-ai/concepts/test-candidate.md"
    resp = client.post(
        "/wiki/edge-ai/move",
        data={"rel_path": src_rel, "target_domain": "robotics"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert not (wiki_root / src_rel).exists()
    tgt = wiki_root / "domains/robotics/concepts/test-candidate.md"
    assert tgt.exists()
    body = tgt.read_text(encoding="utf-8")
    assert "domain: robotics" in body
    assert resp.headers["location"].endswith(
        "/wiki/robotics/page/domains/robotics/concepts/test-candidate.md"
    )
    audit = (wiki_root / "audit/approvals.log").read_text()
    assert "move-page" in audit
    assert "domains/robotics" in (wiki_root / "domains/edge-ai/log.md").read_text()
    assert "domains/edge-ai" in (wiki_root / "domains/robotics/log.md").read_text()


def test_wiki_move_rejects_same_domain(client, wiki_root):
    _approve_test_candidate(client)
    resp = client.post(
        "/wiki/edge-ai/move",
        data={"rel_path": "domains/edge-ai/concepts/test-candidate.md",
              "target_domain": "edge-ai"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_wiki_move_rejects_unknown_target_domain(client, wiki_root):
    _approve_test_candidate(client)
    resp = client.post(
        "/wiki/edge-ai/move",
        data={"rel_path": "domains/edge-ai/concepts/test-candidate.md",
              "target_domain": "does-not-exist"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_wiki_move_rejects_collision(client, wiki_root):
    _setup_second_domain(wiki_root, "robotics")
    _approve_test_candidate(client)
    collision = wiki_root / "domains/robotics/concepts/test-candidate.md"
    collision.write_text("existing\n")
    resp = client.post(
        "/wiki/edge-ai/move",
        data={"rel_path": "domains/edge-ai/concepts/test-candidate.md",
              "target_domain": "robotics"},
        follow_redirects=False,
    )
    assert resp.status_code == 409
    # Source must remain intact on collision
    assert (wiki_root / "domains/edge-ai/concepts/test-candidate.md").exists()


def test_wiki_move_refuses_metadata_file(client, wiki_root):
    resp = client.post(
        "/wiki/edge-ai/move",
        data={"rel_path": "domains/edge-ai/log.md",
              "target_domain": "robotics"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_candidate_edit_saves(client, wiki_root):
    edited = """---
title: "Edited Title"
domain: edge-ai
type: concept
status: candidate
confidence: 0.80
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:40:00+00:00"
tags: [edited]
candidate_id: cand_edited
candidate_operation: create
target_path: domains/edge-ai/concepts/edited.md
raw_ids: []
---
# Edited body
"""
    resp = client.post("/candidates/edge-ai/cand_test.md/edit",
                       data={"raw_content": edited},
                       follow_redirects=False)
    assert resp.status_code in (302, 303)
    saved = (wiki_root / "candidates/edge-ai/pending/cand_test.md").read_text()
    assert "Edited Title" in saved
