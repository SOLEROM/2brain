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


def test_approve_strips_candidate_only_fields(repo_root):
    _setup_candidate(repo_root)
    approve_candidate("cand_test.md", "edge-ai", reviewed_by="vlad", repo_root=repo_root)
    target = repo_root / "domains" / "edge-ai" / "concepts" / "nnapi-concept.md"
    content = target.read_text()
    # Match whole-line form so origin_candidate_id doesn't give a false positive.
    lines = content.splitlines()
    for banned in ["candidate_operation:", "target_path:", "raw_ids:"]:
        assert not any(line.startswith(banned) for line in lines), \
            f"Approved page leaks candidate field: {banned}"
    assert not any(line.startswith("candidate_id:") for line in lines)
    assert "origin_candidate_id: cand_20260416_153000_nnapi-concept_a1b2c3d4" in content


def test_reject_writes_audit_log(repo_root):
    _setup_candidate(repo_root)
    reject_candidate("cand_test.md", "edge-ai", reason="off topic",
                     reviewed_by="vlad", repo_root=repo_root)
    audit = (repo_root / "audit" / "approvals.log").read_text()
    assert "reject" in audit
    assert "off topic" in audit


def test_approve_writes_audit_log(repo_root):
    _setup_candidate(repo_root)
    approve_candidate("cand_test.md", "edge-ai", reviewed_by="vlad", repo_root=repo_root)
    audit = (repo_root / "audit" / "approvals.log").read_text()
    assert "approve" in audit
    assert "cand_test.md" in audit


def test_approve_archive_operation_moves_existing_page(repo_root):
    """candidate_operation: archive should move the approved page to .archive/."""
    concepts = repo_root / "domains" / "edge-ai" / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    (repo_root / "domains" / "edge-ai" / "log.md").write_text("# Log\n")
    (repo_root / "candidates" / "edge-ai" / "archived").mkdir(parents=True, exist_ok=True)
    pending = repo_root / "candidates" / "edge-ai" / "pending"
    pending.mkdir(parents=True, exist_ok=True)

    approved = concepts / "deprecated.md"
    approved.write_text("""---
title: "Deprecated"
domain: edge-ai
type: concept
status: approved
confidence: 0.5
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags: []
---
old content
""")
    archive_cand = """---
title: "Archive Deprecated"
domain: edge-ai
type: concept
status: candidate
confidence: 0.5
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags: []
candidate_id: cand_a
candidate_operation: archive
target_path: domains/edge-ai/concepts/deprecated.md
raw_ids: []
---
Archive rationale.
"""
    (pending / "cand_arch.md").write_text(archive_cand)
    approve_candidate("cand_arch.md", "edge-ai", reviewed_by="vlad", repo_root=repo_root)
    assert not approved.exists()
    archived = repo_root / "domains" / "edge-ai" / ".archive" / "deprecated.md"
    assert archived.exists()
    assert "status: archived" in archived.read_text()


def test_approve_with_drop_raw_removes_raw_sources(repo_root):
    """drop_raw=True deletes inbox/raw/<raw_id>/ after a successful create."""
    pending = repo_root / "candidates" / "edge-ai" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (repo_root / "candidates" / "edge-ai" / "archived").mkdir(parents=True, exist_ok=True)
    (repo_root / "domains" / "edge-ai" / "concepts").mkdir(parents=True, exist_ok=True)
    (repo_root / "domains" / "edge-ai" / "log.md").write_text("# Log\n")

    # Set up the raw folder that the candidate cites.
    raw_id = "raw_20260417_test_dropapproval_deadbeef"
    raw_dir = repo_root / "inbox" / "raw" / raw_id
    raw_dir.mkdir(parents=True)
    (raw_dir / "source.md").write_text("source content")

    cand = f"""---
title: "Drop Test"
domain: edge-ai
type: concept
status: candidate
confidence: 0.6
sources: []
created_at: "2026-04-17T12:00:00+00:00"
updated_at: "2026-04-17T12:00:00+00:00"
tags: []
candidate_id: cand_drop_test
candidate_operation: create
target_path: domains/edge-ai/concepts/drop-test.md
raw_ids:
  - {raw_id}
---
# Drop Test
"""
    (pending / "cand_drop.md").write_text(cand)
    approve_candidate(
        "cand_drop.md", "edge-ai",
        reviewed_by="vlad", repo_root=repo_root, drop_raw=True,
    )

    # Approved page exists, raw folder gone.
    assert (repo_root / "domains/edge-ai/concepts/drop-test.md").exists()
    assert not raw_dir.exists()

    # Audit log records the drop.
    audit = (repo_root / "audit" / "approvals.log").read_text()
    assert "drop-raw-on-approve" in audit
    assert raw_id in audit


def test_approve_without_drop_raw_preserves_raw_source(repo_root):
    """Default approve (drop_raw=False) leaves the raw folder intact."""
    pending = repo_root / "candidates" / "edge-ai" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    (repo_root / "candidates" / "edge-ai" / "archived").mkdir(parents=True, exist_ok=True)
    (repo_root / "domains" / "edge-ai" / "concepts").mkdir(parents=True, exist_ok=True)
    (repo_root / "domains" / "edge-ai" / "log.md").write_text("# Log\n")

    raw_id = "raw_20260417_test_keepraw_cafebabe"
    raw_dir = repo_root / "inbox" / "raw" / raw_id
    raw_dir.mkdir(parents=True)
    (raw_dir / "source.md").write_text("source content")

    cand = f"""---
title: "Keep Test"
domain: edge-ai
type: concept
status: candidate
confidence: 0.6
sources: []
created_at: "2026-04-17T12:00:00+00:00"
updated_at: "2026-04-17T12:00:00+00:00"
tags: []
candidate_id: cand_keep_test
candidate_operation: create
target_path: domains/edge-ai/concepts/keep-test.md
raw_ids:
  - {raw_id}
---
# Keep Test
"""
    (pending / "cand_keep.md").write_text(cand)
    approve_candidate(
        "cand_keep.md", "edge-ai",
        reviewed_by="vlad", repo_root=repo_root,
    )

    assert (repo_root / "domains/edge-ai/concepts/keep-test.md").exists()
    assert raw_dir.exists()


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
