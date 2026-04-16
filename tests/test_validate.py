import pytest
from pathlib import Path
from src.validate import validate_frontmatter, parse_frontmatter, check_path_traversal

VALID_PAGE = """\
---
title: "Test Page"
domain: edge-ai
type: concept
status: candidate
confidence: 0.75
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags:
  - test
---

# Test Page

## Summary
Content here.
"""

MISSING_CONFIDENCE = """\
---
title: "Test Page"
domain: edge-ai
type: concept
status: candidate
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags: []
---
Content.
"""

INVALID_CONFIDENCE = """\
---
title: "Test Page"
domain: edge-ai
type: concept
status: candidate
confidence: 1.5
sources: []
created_at: "2026-04-16T15:30:00+00:00"
updated_at: "2026-04-16T15:30:00+00:00"
tags: []
---
Content.
"""


def test_valid_page(tmp_path):
    p = tmp_path / "page.md"
    p.write_text(VALID_PAGE)
    result = validate_frontmatter(p)
    assert result.valid
    assert result.errors == []


def test_missing_confidence(tmp_path):
    p = tmp_path / "page.md"
    p.write_text(MISSING_CONFIDENCE)
    result = validate_frontmatter(p)
    assert not result.valid
    assert any("confidence" in e for e in result.errors)


def test_invalid_confidence_range(tmp_path):
    p = tmp_path / "page.md"
    p.write_text(INVALID_CONFIDENCE)
    result = validate_frontmatter(p)
    assert not result.valid


def test_parse_frontmatter_extracts_body(tmp_path):
    p = tmp_path / "page.md"
    p.write_text(VALID_PAGE)
    fm, body = parse_frontmatter(p)
    assert fm["title"] == "Test Page"
    assert "# Test Page" in body


def test_parse_frontmatter_no_frontmatter(tmp_path):
    p = tmp_path / "page.md"
    p.write_text("# Just markdown\nNo frontmatter.")
    fm, body = parse_frontmatter(p)
    assert fm == {}
    assert "# Just markdown" in body


def test_check_path_traversal_valid():
    assert check_path_traversal("domains/edge-ai/concepts/nnapi.md", "edge-ai") is True


def test_check_path_traversal_invalid():
    assert check_path_traversal("../../../etc/passwd", "edge-ai") is False
    assert check_path_traversal("domains/other-domain/concepts/x.md", "edge-ai") is False
    assert check_path_traversal("/absolute/path.md", "edge-ai") is False
