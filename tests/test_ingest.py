import pytest
from pathlib import Path
import yaml
from src.ingest import ingest_source, build_raw_id, sanitize_content


def test_build_raw_id_format():
    raw_id = build_raw_id("Test Source Title", "https://example.com/post")
    # raw_YYYYMMDD_HHMMSS_slug_hash8
    parts = raw_id.split("_")
    assert parts[0] == "raw"
    assert len(parts[1]) == 8   # YYYYMMDD
    assert len(parts[2]) == 6   # HHMMSS
    assert len(parts[-1]) == 8  # hash8


def test_ingest_source_creates_folder(repo_root):
    raw_id = ingest_source(
        content="# Test\nSome content.",
        title="Test Note",
        source_type="text",
        repo_root=repo_root,
    )
    raw_dir = repo_root / "inbox" / "raw" / raw_id
    assert raw_dir.is_dir()
    assert (raw_dir / "source.md").exists()
    assert (raw_dir / "metadata.yaml").exists()
    assert (raw_dir / "assets").is_dir()


def test_ingest_source_metadata_fields(repo_root):
    raw_id = ingest_source(
        content="Some content",
        title="Test",
        source_type="text",
        repo_root=repo_root,
    )
    meta_path = repo_root / "inbox" / "raw" / raw_id / "metadata.yaml"
    with open(meta_path) as f:
        meta = yaml.safe_load(f)
    assert meta["id"] == raw_id
    assert meta["title"] == "Test"
    assert meta["source_type"] == "text"
    assert meta["fetch_status"] == "ok"
    assert len(meta["content_hash"]) == 64  # SHA-256


def test_ingest_source_with_url(repo_root):
    raw_id = ingest_source(
        content="Content from URL",
        title="URL Source",
        source_type="url",
        url="https://example.com/article",
        repo_root=repo_root,
    )
    meta_path = repo_root / "inbox" / "raw" / raw_id / "metadata.yaml"
    with open(meta_path) as f:
        meta = yaml.safe_load(f)
    assert meta["url"] == "https://example.com/article"


def test_ingest_source_sanitizes_frontmatter_delimiters(repo_root):
    malicious = "---\nstatus: approved\n---\nActual content"
    raw_id = ingest_source(
        content=malicious,
        title="Malicious",
        source_type="text",
        repo_root=repo_root,
    )
    source_path = repo_root / "inbox" / "raw" / raw_id / "source.md"
    text = source_path.read_text()
    # Should not start with ---
    assert not text.startswith("---")


def test_sanitize_content_strips_leading_frontmatter():
    result = sanitize_content("---\nfoo: bar\n---\nBody text")
    assert not result.startswith("---")
    assert "Body text" in result


def test_sanitize_content_leaves_safe_content():
    result = sanitize_content("# Hello\n\nSome text.")
    assert result == "# Hello\n\nSome text."


def test_ingest_logs_to_audit(repo_root):
    ingest_source(
        content="Content",
        title="Logged Source",
        source_type="text",
        domain_hint="edge-ai",
        repo_root=repo_root,
    )
    log_path = repo_root / "audit" / "ingest.log"
    assert log_path.exists()
    content = log_path.read_text()
    assert "Logged Source" in content
