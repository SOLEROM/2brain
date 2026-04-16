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
