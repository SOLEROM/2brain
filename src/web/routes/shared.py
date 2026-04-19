"""Small helpers shared across web routes."""
from pathlib import Path

import yaml

from src.config import load_app_config


def list_domains(repo_root: Path) -> list[str]:
    """Return all domain names that have a domain.yaml. Falls back to ['edge-ai']."""
    domains_dir = repo_root / "domains"
    if not domains_dir.exists():
        return ["edge-ai"]
    found = sorted(
        d.name for d in domains_dir.iterdir()
        if d.is_dir() and (d / "domain.yaml").exists()
    )
    return found or ["edge-ai"]


def default_domain(repo_root: Path) -> str:
    cfg = load_app_config(repo_root=repo_root)
    d = cfg.get("default_domain")
    if d:
        return str(d)
    domains = list_domains(repo_root)
    return domains[0] if domains else "edge-ai"


SESSION_DOMAIN_COOKIE = "2brain-domain"


def current_domain(request, repo_root: Path) -> str:
    """Resolve the active domain for this request.

    Priority: cookie `2brain-domain` (if it names a known domain) → default_domain.
    Routes with a `{domain}` path param pass that value directly to templates;
    this helper covers routes that don't have one (digest, ingest, jobs, config).
    """
    try:
        cookie = request.cookies.get(SESSION_DOMAIN_COOKIE)
    except Exception:
        cookie = None
    if cookie and cookie in list_domains(repo_root):
        return cookie
    return default_domain(repo_root)


def get_source_types(repo_root: Path) -> list[str]:
    cfg = load_app_config(repo_root=repo_root)
    types = cfg.get("source_types") or []
    return [str(t) for t in types]


def get_suggested_tags(repo_root: Path) -> list[str]:
    cfg = load_app_config(repo_root=repo_root)
    tags = cfg.get("suggested_tags") or []
    return [str(t) for t in tags]


def get_ui_settings(repo_root: Path) -> dict:
    cfg = load_app_config(repo_root=repo_root)
    return cfg.get("ui") or {}


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def template_context(request, **kwargs) -> dict:
    """Build a template context with sensible defaults (domain, domains)."""
    repo_root: Path = request.app.state.repo_root
    ctx = {
        "domains": list_domains(repo_root),
        "default_domain": default_domain(repo_root),
    }
    ctx.update(kwargs)
    if "domain" not in ctx:
        ctx["domain"] = ctx["default_domain"]
    return ctx
