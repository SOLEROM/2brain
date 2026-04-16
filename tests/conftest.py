import pytest
from pathlib import Path


@pytest.fixture
def repo_root(tmp_path):
    """A temp directory mimicking the 2brain repo root."""
    for d in ["inbox/raw", "candidates", "domains", "jobs/queued",
              "jobs/running", "jobs/completed", "jobs/failed", "audit"]:
        (tmp_path / d).mkdir(parents=True)
    return tmp_path
