"""Application configuration.

Single source of truth for all tunable params. Defaults live here; any key
may be overridden by `config/app.yaml` at the repo root.
"""
from copy import deepcopy
from pathlib import Path
from typing import Optional

import yaml


DEFAULT_APP_CONFIG: dict = {
    "version": "1",
    "repo_root": ".",
    "default_domain": "edge-ai",

    "web_ui": {
        "host": "127.0.0.1",
        "port": 5000,
        "auto_open_browser": False,
    },

    "audit": {
        "enabled": True,
        "log_queries": False,
    },

    # Ingest form — source types shown in the dropdown.
    "source_types": ["url", "text", "note", "pdf", "repo", "image", "video", "api"],

    # Tag suggestions surfaced in ingest / candidate editing.
    "suggested_tags": [],

    # Digest agent limits.
    "digest": {
        "max_source_chars": 40000,
        "max_tokens": 4096,
    },

    # Lint / health check thresholds.
    "lint": {
        "stale_days": 90,
        "stuck_job_minutes": 10,
        "low_confidence_threshold": 0.35,
    },

    # UI theme preferences. `default_theme` is applied server-side before JS
    # runs (so the very first paint matches). Users may still toggle.
    "ui": {
        "default_theme": "light",
        "themes": ["light", "dark", "hackers-green"],
    },
}


def app_config_path(repo_root: Path = Path(".")) -> Path:
    return repo_root / "config" / "app.yaml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict: `base` with `override` applied.

    Nested dicts are merged recursively; lists and scalars are replaced.
    """
    out = deepcopy(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = deepcopy(val)
    return out


def load_app_config(
    path: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> dict:
    """Load merged config (defaults + file overrides).

    Missing file, empty file, or parse errors fall back to defaults so the
    app still runs.
    """
    if path is None:
        path = app_config_path(repo_root if repo_root is not None else Path("."))
    if not path.exists():
        return deepcopy(DEFAULT_APP_CONFIG)
    try:
        user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        user = {}
    if not isinstance(user, dict):
        user = {}
    return _deep_merge(DEFAULT_APP_CONFIG, user)


def dump_app_config(cfg: dict) -> str:
    return yaml.dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False)


def load_agents_config(path: Path = Path("config/agents.yaml")) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)
