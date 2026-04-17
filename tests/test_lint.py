import pytest
from pathlib import Path
from src.lint import lint_domain, LintReport

LOW_CONFIDENCE_PAGE = """\
---
title: "Low Confidence Page"
domain: edge-ai
type: concept
status: approved
confidence: 0.25
sources: []
created_at: "2026-04-16T12:00:00+00:00"
updated_at: "2026-04-16T12:00:00+00:00"
tags: []
---
# Low Confidence Page
Content.
"""

CONTRADICTION_PAGE = """\
---
title: "Page With Contradiction"
domain: edge-ai
type: concept
status: approved
confidence: 0.70
sources: []
created_at: "2026-04-16T12:00:00+00:00"
updated_at: "2026-04-16T12:00:00+00:00"
tags: []
---
# Page With Contradiction

> [!contradiction]
> **Conflict:** This says X but other says Y.
> **Status:** unresolved
"""

NORMAL_PAGE = """\
---
title: "Normal Page"
domain: edge-ai
type: concept
status: approved
confidence: 0.80
sources: []
created_at: "2026-04-16T12:00:00+00:00"
updated_at: "2026-04-16T12:00:00+00:00"
tags: []
---
# Normal Page
See also [[Low Confidence Page]].
"""


def _setup_domain(repo_root: Path):
    concepts = repo_root / "domains" / "edge-ai" / "concepts"
    concepts.mkdir(parents=True)
    indexes = repo_root / "domains" / "edge-ai" / "indexes"
    indexes.mkdir(parents=True)
    (repo_root / "candidates" / "edge-ai" / "pending").mkdir(parents=True)
    (concepts / "low-confidence-page.md").write_text(LOW_CONFIDENCE_PAGE)
    (concepts / "page-with-contradiction.md").write_text(CONTRADICTION_PAGE)
    (concepts / "normal-page.md").write_text(NORMAL_PAGE)
    (repo_root / "domains" / "edge-ai" / "index.md").write_text("# Index\n")
    (repo_root / "domains" / "edge-ai" / "log.md").write_text("# Log\n")


def test_lint_finds_low_confidence(repo_root):
    _setup_domain(repo_root)
    report = lint_domain("edge-ai", repo_root=repo_root)
    assert len(report.low_confidence_pages) >= 1
    titles = [p["title"] for p in report.low_confidence_pages]
    assert "Low Confidence Page" in titles


def test_lint_finds_contradictions(repo_root):
    _setup_domain(repo_root)
    report = lint_domain("edge-ai", repo_root=repo_root)
    assert len(report.unresolved_contradictions) >= 1


def test_lint_writes_low_confidence_index(repo_root):
    _setup_domain(repo_root)
    lint_domain("edge-ai", repo_root=repo_root)
    index = repo_root / "domains" / "edge-ai" / "indexes" / "low-confidence.md"
    assert index.exists()
    assert "Low Confidence Page" in index.read_text()


def test_lint_writes_contradictions_index(repo_root):
    _setup_domain(repo_root)
    lint_domain("edge-ai", repo_root=repo_root)
    index = repo_root / "domains" / "edge-ai" / "indexes" / "contradictions.md"
    assert index.exists()
    assert "Page With Contradiction" in index.read_text()


def test_lint_finds_orphans(repo_root):
    _setup_domain(repo_root)
    report = lint_domain("edge-ai", repo_root=repo_root)
    # "Page With Contradiction" is not linked by any other page
    orphan_titles = [p["title"] for p in report.orphans]
    assert "Page With Contradiction" in orphan_titles


def test_lint_writes_orphans_index(repo_root):
    _setup_domain(repo_root)
    lint_domain("edge-ai", repo_root=repo_root)
    index = repo_root / "domains" / "edge-ai" / "indexes" / "orphans.md"
    assert index.exists()


def test_lint_finds_stuck_jobs(repo_root):
    _setup_domain(repo_root)
    running = repo_root / "jobs" / "running"
    running.mkdir(parents=True, exist_ok=True)
    stuck = """job_id: job_20250101_000000_digest_deadbeef
job_type: digest
domain: edge-ai
status: running
created_at: "2025-01-01T00:00:00+00:00"
started_at: "2025-01-01T00:00:00+00:00"
heartbeat_at: "2025-01-01T00:00:00+00:00"
input: raw_x
outputs: []
agent: digest-agent
"""
    (running / "stuck.yaml").write_text(stuck)
    report = lint_domain("edge-ai", repo_root=repo_root)
    assert len(report.stuck_jobs) >= 1


def test_lint_finds_stale_candidates(repo_root):
    _setup_domain(repo_root)
    # Write a domain.yaml with a short max age
    (repo_root / "domains" / "edge-ai" / "domain.yaml").write_text("max_candidate_age_days: 1\n")
    pending = repo_root / "candidates" / "edge-ai" / "pending"
    old_cand = """---
title: "Stale"
domain: edge-ai
type: concept
status: candidate
confidence: 0.5
sources: []
created_at: "2025-01-01T00:00:00+00:00"
updated_at: "2025-01-01T00:00:00+00:00"
tags: []
candidate_id: cand_stale
candidate_operation: create
target_path: domains/edge-ai/concepts/stale.md
raw_ids: []
---
body
"""
    (pending / "cand_stale.md").write_text(old_cand)
    report = lint_domain("edge-ai", repo_root=repo_root)
    assert any(c["filename"] == "cand_stale.md" for c in report.stale_candidates)
