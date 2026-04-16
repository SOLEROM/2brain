import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import yaml
from src.digest import (
    digest_raw, build_candidate_id, build_digest_prompt,
    write_candidate, find_near_duplicates
)
from src.ingest import ingest_source


def test_build_candidate_id_format():
    cid = build_candidate_id("Test Candidate Title", "some content")
    parts = cid.replace(".md", "").split("_")
    assert parts[0] == "cand"
    assert len(parts[1]) == 8   # YYYYMMDD
    assert len(parts[2]) == 6   # HHMMSS
    assert len(parts[-1]) == 8  # hash8


def test_build_digest_prompt_includes_schema(repo_root):
    # Create domain structure
    domain_dir = repo_root / "domains" / "edge-ai"
    domain_dir.mkdir(parents=True)
    (domain_dir / "schema.md").write_text("# Schema\nConcepts: chip, board.")

    prompt = build_digest_prompt(
        raw_content="Some article about NPUs.",
        raw_id="raw_20260416_153042_test_a91f03bc",
        domain="edge-ai",
        repo_root=repo_root,
    )
    assert "# Schema" in prompt
    assert "Some article about NPUs." in prompt
    assert "raw_20260416_153042_test_a91f03bc" in prompt


def test_write_candidate_creates_file(repo_root):
    domain = "edge-ai"
    (repo_root / "candidates" / domain / "pending").mkdir(parents=True)

    page_content = """\
---
title: "Test Candidate"
domain: edge-ai
type: concept
status: candidate
confidence: 0.72
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags: [test]
candidate_id: cand_20260416_153000_test-candidate_a1b2c3d4
candidate_operation: create
target_path: domains/edge-ai/concepts/test-candidate.md
raw_ids: []
---

# Test Candidate

## Summary
Test content.
"""
    cand_id = write_candidate(page_content, domain, repo_root)
    pending_dir = repo_root / "candidates" / domain / "pending"
    files = list(pending_dir.glob("*.md"))
    assert len(files) == 1
    assert cand_id in files[0].name


def test_find_near_duplicates_empty(repo_root):
    domain_dir = repo_root / "domains" / "edge-ai"
    domain_dir.mkdir(parents=True)
    (repo_root / "candidates" / "edge-ai" / "pending").mkdir(parents=True)

    dupes = find_near_duplicates("NNAPI Delegate", "edge-ai", repo_root)
    assert dupes == []


def test_find_near_duplicates_finds_match(repo_root):
    domain_dir = repo_root / "domains" / "edge-ai" / "concepts"
    domain_dir.mkdir(parents=True)
    (repo_root / "candidates" / "edge-ai" / "pending").mkdir(parents=True)

    existing = domain_dir / "nnapi-delegate.md"
    existing.write_text("""\
---
title: NNAPI Delegate
domain: edge-ai
type: concept
status: approved
confidence: 0.8
sources: []
created_at: "2026-04-16T12:00:00+00:00"
updated_at: "2026-04-16T12:00:00+00:00"
tags: [nnapi]
---
# NNAPI Delegate
""")
    dupes = find_near_duplicates("NNAPI Delegate", "edge-ai", repo_root)
    assert len(dupes) > 0
    assert "nnapi-delegate.md" in dupes[0]


@patch("src.digest.anthropic.Anthropic")
def test_digest_raw_calls_claude(mock_anthropic_cls, repo_root):
    """digest_raw calls Claude and writes a candidate file."""
    # Set up raw source
    raw_id = ingest_source(
        content="# NNAPI Overview\nNNAPI is an Android ML API.",
        title="NNAPI Overview",
        source_type="text",
        domain_hint="edge-ai",
        repo_root=repo_root,
    )

    # Set up domain
    domain_dir = repo_root / "domains" / "edge-ai"
    domain_dir.mkdir(parents=True, exist_ok=True)
    (domain_dir / "schema.md").write_text("# Edge AI Schema")
    (repo_root / "candidates" / "edge-ai" / "pending").mkdir(parents=True, exist_ok=True)
    (repo_root / "jobs" / "completed").mkdir(parents=True, exist_ok=True)

    # Copy agents.yaml into the tmp repo_root so load_agents_config finds it
    import shutil
    (repo_root / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy(Path("config/agents.yaml"), repo_root / "config" / "agents.yaml")

    # Mock Claude response
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="""\
---
title: "NNAPI Overview"
domain: edge-ai
type: concept
status: candidate
confidence: 0.75
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags: [nnapi]
candidate_id: cand_20260416_153000_nnapi-overview_a1b2c3d4
candidate_operation: create
target_path: domains/edge-ai/concepts/nnapi-overview.md
raw_ids: []
---

# NNAPI Overview

## Summary
NNAPI is an Android ML API.

## Key Claims
- NNAPI is an Android API.
  **Confidence:** 0.75
  **Evidence:** source text
  **Evidence type:** direct
""")]
    )

    candidate_ids = digest_raw(raw_id, "edge-ai", repo_root=repo_root)
    assert len(candidate_ids) >= 1
    mock_client.messages.create.assert_called_once()
