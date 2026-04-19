import pytest
from pathlib import Path
import yaml
from src.ingest import ingest_source, build_raw_id, sanitize_content
from src.web.routes.ingest_routes import (
    _extract_media_urls,
    _record_media_in_metadata,
    _safe_asset_filename,
    parse_github_url,
)


@pytest.mark.parametrize("url,want_kind,want_fields", [
    ("https://github.com/anthropics/claude-cookbooks", "repo",
     {"owner": "anthropics", "repo": "claude-cookbooks"}),
    ("http://github.com/foo/bar.git", "repo", {"owner": "foo", "repo": "bar"}),
    ("https://www.github.com/foo/bar/", "repo", {"owner": "foo", "repo": "bar"}),
    ("https://github.com/foo/bar?ref=main", "repo", {"owner": "foo", "repo": "bar"}),
    ("https://github.com/foo/bar/blob/main/src/app.py", "blob",
     {"owner": "foo", "repo": "bar", "branch": "main", "path": "src/app.py"}),
])
def test_parse_github_url_matches(url, want_kind, want_fields):
    got = parse_github_url(url)
    assert got is not None, f"expected match for {url}"
    assert got[0] == want_kind
    for k, v in want_fields.items():
        assert got[1][k] == v


@pytest.mark.parametrize("url", [
    "https://example.com/foo/bar",
    "https://github.com/foo",
    "https://github.com/foo/bar/tree/main",  # tree URL — not handled here
    "",
])
def test_parse_github_url_non_matches(url):
    assert parse_github_url(url) is None


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


def test_extract_media_urls_from_html():
    html = '''
    <html><body>
      <img src="/images/diagram.png" alt="d">
      <img src="https://cdn.example.com/hero.jpg?v=3">
      <a href="/files/spec.pdf">spec</a>
      <video src="clip.mp4" poster="poster.webp"></video>
      <img src="data:image/png;base64,AAAA">
      <img src="/images/diagram.png">   <!-- duplicate -->
    </body></html>
    '''
    urls = _extract_media_urls(html, "https://example.com/docs/")
    assert "https://example.com/images/diagram.png" in urls
    assert "https://cdn.example.com/hero.jpg" in urls
    assert "https://example.com/files/spec.pdf" in urls
    assert "https://example.com/docs/clip.mp4" in urls
    assert "https://example.com/docs/poster.webp" in urls
    assert not any(u.startswith("data:") for u in urls)
    # De-duplicated
    assert len(urls) == len(set(urls))


def test_extract_media_urls_from_markdown():
    md = "Here is a diagram: ![d](https://example.com/x.png)\n![](./rel.jpg)"
    urls = _extract_media_urls(md, "https://example.com/post/")
    assert "https://example.com/x.png" in urls
    assert "https://example.com/post/rel.jpg" in urls


def test_safe_asset_filename_deterministic_and_suffixed():
    url = "https://example.com/path/weird%20name.png"
    a = _safe_asset_filename(url)
    b = _safe_asset_filename(url)
    assert a == b  # deterministic
    assert a.endswith(".png")
    assert " " not in a and "?" not in a


def test_record_media_in_metadata_roundtrips(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    meta_path = raw_dir / "metadata.yaml"
    meta_path.write_text(yaml.dump({"id": "r", "tags": ["a"]}), encoding="utf-8")
    _record_media_in_metadata(
        raw_dir,
        [{"url": "https://e/x.png", "file": "x.png", "bytes": 42}],
        attempted=True,
    )
    updated = yaml.safe_load(meta_path.read_text())
    assert updated["download_media"] is True
    assert updated["media_assets"][0]["file"] == "x.png"
    assert updated["tags"] == ["a"]  # pre-existing keys preserved


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
