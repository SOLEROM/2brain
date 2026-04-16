import pytest
from pathlib import Path
from src.models import RawMetadata, PageFrontmatter, JobYaml, ValidationResult
from src.config import load_app_config, load_agents_config


def test_raw_metadata_fields():
    m = RawMetadata(
        id="raw_20260416_153042_test_a91f03bc",
        title="Test Source",
        source_type="url",
        origin="manual",
        url="https://example.com",
        submitted_by="user",
        ingested_at="2026-04-16T15:30:42+00:00",
        content_hash="abc123",
        domain_hint="edge-ai",
        tags=[],
        fetch_status="ok",
    )
    assert m.id.startswith("raw_")


def test_page_frontmatter_valid():
    fm = PageFrontmatter(
        title="Test Page",
        domain="edge-ai",
        type="concept",
        status="candidate",
        confidence=0.75,
        sources=[],
        created_at="2026-04-16T15:30:00+00:00",
        updated_at="2026-04-16T15:30:00+00:00",
        tags=["test"],
    )
    assert fm.confidence == 0.75


def test_page_frontmatter_confidence_bounds():
    with pytest.raises(Exception):
        PageFrontmatter(
            title="T", domain="d", type="concept", status="candidate",
            confidence=1.5, sources=[], created_at="x", updated_at="x", tags=[],
        )


def test_page_frontmatter_invalid_status():
    with pytest.raises(Exception):
        PageFrontmatter(
            title="T", domain="d", type="concept", status="invalid",
            confidence=0.5, sources=[], created_at="x", updated_at="x", tags=[],
        )


def test_job_yaml_fields():
    job = JobYaml(
        job_id="job_20260416_153042_digest_a91f03bc",
        job_type="digest",
        domain="edge-ai",
        status="queued",
        created_at="2026-04-16T15:30:42+00:00",
        input="raw_20260416_153042_test_a91f03bc",
    )
    assert job.status == "queued"


def test_load_app_config():
    cfg = load_app_config(Path("config/app.yaml"))
    assert cfg["web_ui"]["port"] == 5000


def test_load_agents_config():
    cfg = load_agents_config(Path("config/agents.yaml"))
    assert cfg["digest_agent"]["model"] == "claude-sonnet-4-6"
