import pytest
from pathlib import Path
import yaml
from src.approval import approve_candidate, reject_candidate, archive_candidate, list_pending

VALID_CANDIDATE = """\
---
title: "NNAPI Concept"
domain: edge-ai
type: concept
status: candidate
confidence: 0.75
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags:
  - nnapi
candidate_id: cand_20260416_153000_nnapi-concept_a1b2c3d4
candidate_operation: create
target_path: domains/edge-ai/concepts/nnapi-concept.md
raw_ids: []
---

# NNAPI Concept

## Summary
NNAPI content.
"""


def _setup_candidate(repo_root: Path, cand_filename: str = "cand_test.md") -> Path:
    pending = repo_root / "candidates" / "edge-ai" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (repo_root / "candidates" / "edge-ai" / "archived").mkdir(parents=True, exist_ok=True)
    (repo_root / "candidates" / "edge-ai" / "rejected").mkdir(parents=True, exist_ok=True)
    (repo_root / "domains" / "edge-ai" / "concepts").mkdir(parents=True, exist_ok=True)
    (repo_root / "domains" / "edge-ai" / "log.md").write_text("# Log\n")
    (repo_root / "domains" / "edge-ai" / "index.md").write_text("# Index\n")
    cand_path = pending / cand_filename
    cand_path.write_text(VALID_CANDIDATE)
    return cand_path


def test_approve_creates_target_file(repo_root):
    _setup_candidate(repo_root)
    approve_candidate("cand_test.md", "edge-ai", reviewed_by="vlad", repo_root=repo_root)
    target = repo_root / "domains" / "edge-ai" / "concepts" / "nnapi-concept.md"
    assert target.exists()


def test_approve_sets_status_approved(repo_root):
    _setup_candidate(repo_root)
    approve_candidate("cand_test.md", "edge-ai", reviewed_by="vlad", repo_root=repo_root)
    target = repo_root / "domains" / "edge-ai" / "concepts" / "nnapi-concept.md"
    content = target.read_text()
    assert "status: approved" in content


def test_approve_sets_reviewed_fields(repo_root):
    _setup_candidate(repo_root)
    approve_candidate("cand_test.md", "edge-ai", reviewed_by="vlad", repo_root=repo_root)
    target = repo_root / "domains" / "edge-ai" / "concepts" / "nnapi-concept.md"
    content = target.read_text()
    assert "reviewed_by: vlad" in content
    assert "reviewed_at:" in content


def test_approve_archives_candidate(repo_root):
    _setup_candidate(repo_root)
    approve_candidate("cand_test.md", "edge-ai", reviewed_by="vlad", repo_root=repo_root)
    pending = repo_root / "candidates" / "edge-ai" / "pending" / "cand_test.md"
    archived = repo_root / "candidates" / "edge-ai" / "archived" / "cand_test.md"
    assert not pending.exists()
    assert archived.exists()


def test_approve_updates_log(repo_root):
    _setup_candidate(repo_root)
    approve_candidate("cand_test.md", "edge-ai", reviewed_by="vlad", repo_root=repo_root)
    log = (repo_root / "domains" / "edge-ai" / "log.md").read_text()
    assert "approve" in log
    assert "NNAPI Concept" in log


def test_reject_moves_to_rejected(repo_root):
    _setup_candidate(repo_root)
    reject_candidate("cand_test.md", "edge-ai", repo_root=repo_root)
    rejected = repo_root / "candidates" / "edge-ai" / "rejected" / "cand_test.md"
    assert rejected.exists()
    pending = repo_root / "candidates" / "edge-ai" / "pending" / "cand_test.md"
    assert not pending.exists()


def test_list_pending_returns_filenames(repo_root):
    _setup_candidate(repo_root)
    pending = list_pending("edge-ai", repo_root=repo_root)
    assert "cand_test.md" in pending


def test_approve_rejects_path_traversal(repo_root):
    pending = repo_root / "candidates" / "edge-ai" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (repo_root / "candidates" / "edge-ai" / "archived").mkdir(parents=True, exist_ok=True)
    traversal_candidate = """\
---
title: "Evil"
domain: edge-ai
type: concept
status: candidate
confidence: 0.5
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags: []
candidate_id: cand_20260416_153000_evil_a1b2c3d4
candidate_operation: create
target_path: "../../../etc/evil.md"
raw_ids: []
---
Evil content.
"""
    (pending / "cand_evil.md").write_text(traversal_candidate)
    with pytest.raises(ValueError, match="Invalid target_path"):
        approve_candidate("cand_evil.md", "edge-ai", reviewed_by="vlad", repo_root=repo_root)
