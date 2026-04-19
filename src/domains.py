"""Domain lifecycle helpers — create and rename.

Delete is deliberately absent: approved knowledge is the point of the app,
and a misclick should never take a whole domain with it. Use git.

Both operations are "cascading": a rename doesn't just move one folder,
it also updates the candidates tree, per-page frontmatter, the app-level
``default_domain`` setting, agent ``config.yaml`` files that pin the
domain, and best-effort ``seen.json`` path references.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from src.utils import atomic_write, now_iso
from src.validate import parse_frontmatter


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RESERVED_NAMES = {".archive", "indexes"}


class DomainError(ValueError):
    """Raised for domain-create/rename validation or cascade failures."""


def _normalise(name: str) -> str:
    return (name or "").strip().lower()


def _list_domain_names(repo_root: Path) -> list[str]:
    d = repo_root / "domains"
    if not d.exists():
        return []
    return sorted(
        child.name for child in d.iterdir()
        if child.is_dir() and (child / "domain.yaml").exists()
    )


def validate_new_domain_name(name: str, repo_root: Path) -> str:
    """Return canonical name or raise DomainError."""
    canon = _normalise(name)
    if not canon:
        raise DomainError("Domain name is required.")
    if not SLUG_RE.match(canon):
        raise DomainError(
            "Invalid domain name. Use lowercase letters, numbers, and hyphens "
            "(max 40 chars). Example: `edge-ai`.",
        )
    if canon in RESERVED_NAMES:
        raise DomainError(f"'{canon}' is reserved and can't be used as a domain.")
    if canon in _list_domain_names(repo_root):
        raise DomainError(f"Domain '{canon}' already exists.")
    return canon


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------


def _title_case(name: str) -> str:
    parts = name.replace("_", "-").split("-")
    return " ".join(p[:1].upper() + p[1:] for p in parts if p)


def _scaffold_dirs(repo_root: Path, domain: str) -> None:
    domain_dir = repo_root / "domains" / domain
    subdirs = [
        "topics", "concepts", "entities", "sources", "source-summaries",
        "questions", "indexes", ".archive",
        "reports/deep-research", "reports/comparisons", "reports/contradictions",
    ]
    for sub in subdirs:
        (domain_dir / sub).mkdir(parents=True, exist_ok=True)

    cand_root = repo_root / "candidates" / domain
    for sub in ("pending", "rejected", "archived"):
        (cand_root / sub).mkdir(parents=True, exist_ok=True)


def _scaffold_files(repo_root: Path, domain: str) -> None:
    domain_dir = repo_root / "domains" / domain
    display = _title_case(domain)

    dyaml = {
        "name": domain,
        "display_name": display,
        "description": "",
        "default_query_scope": "approved+candidates",
        "confidence_visible": True,
        "approval_unit": "page",
        "contradiction_style": "inline",
        "source_discovery": True,
        "deep_research_enabled": True,
        "max_candidate_age_days": 90,
        "auto_digest": False,
        "web_research": {"enabled": False, "max_sources_per_job": 20},
    }
    atomic_write(
        domain_dir / "domain.yaml",
        yaml.dump(dyaml, allow_unicode=True, sort_keys=False, default_flow_style=False),
    )

    atomic_write(
        domain_dir / "index.md",
        f"# {domain} Index\n\n> Auto-maintained by the wikiLLM agent. Run it "
        f"from the Agents tab to generate a curated landing page.\n",
    )
    atomic_write(
        domain_dir / "log.md",
        f"# {domain} Log\n\n> Append-only. Never delete entries.\n",
    )
    atomic_write(
        domain_dir / "schema.md",
        f"# {display} Domain Schema\n\n"
        "> Edit this file to tell agents how to write pages for this domain.\n\n"
        "## Preferred page types\n- topic\n- concept\n- entity\n- source-summary\n"
        "- comparison\n- research-report\n\n"
        "## Link conventions\n- Link entities to related concepts.\n\n"
        "## Required details\nDescribe any required sections or fields here.\n",
    )

    for fname in (
        "contradictions.md", "low-confidence.md", "stale-pages.md",
        "orphans.md", "suggested-sources.md",
    ):
        (domain_dir / "indexes" / fname).touch()


def create_domain(name: str, repo_root: Path) -> str:
    """Create a new domain tree under ``domains/<name>/``. Returns the name."""
    domain = validate_new_domain_name(name, repo_root)
    _scaffold_dirs(repo_root, domain)
    _scaffold_files(repo_root, domain)
    _append_audit(repo_root, f"create-domain | {domain}")
    return domain


# ---------------------------------------------------------------------------
# RENAME
# ---------------------------------------------------------------------------


@dataclass
class RenameSummary:
    old: str
    new: str
    pages_updated: int
    candidates_updated: int
    agents_updated: list[str]
    app_default_updated: bool
    seen_updated: list[str]


def rename_domain(old: str, new: str, repo_root: Path) -> RenameSummary:
    """Rename a domain across the filesystem, frontmatter, and config.

    This is not atomic — a crash midway can leave a partial state. We
    perform the biggest moves first (folder renames) so a retry with the
    new name works; subsequent cascades are idempotent per-file.
    """
    old_n = _normalise(old)
    if old_n not in _list_domain_names(repo_root):
        raise DomainError(f"Domain '{old_n}' does not exist.")
    new_n = validate_new_domain_name(new, repo_root)
    if old_n == new_n:
        raise DomainError("New name matches the old name.")

    # 1. Folder renames — if either collision happens, abort before touching anything.
    domains_old = repo_root / "domains" / old_n
    domains_new = repo_root / "domains" / new_n
    cands_old = repo_root / "candidates" / old_n
    cands_new = repo_root / "candidates" / new_n
    if domains_new.exists():
        raise DomainError(f"domains/{new_n}/ already exists — refusing to overwrite.")
    if cands_old.exists() and cands_new.exists():
        raise DomainError(f"candidates/{new_n}/ already exists — refusing to overwrite.")

    shutil.move(str(domains_old), str(domains_new))
    if cands_old.exists():
        shutil.move(str(cands_old), str(cands_new))

    # 2. Rewrite domain.yaml (name + display_name if it matched old default).
    dyaml_path = domains_new / "domain.yaml"
    try:
        data = yaml.safe_load(dyaml_path.read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    old_display_match = str(data.get("display_name") or "").strip().lower() == _title_case(old_n).lower()
    data["name"] = new_n
    if old_display_match or not data.get("display_name"):
        data["display_name"] = _title_case(new_n)
    atomic_write(
        dyaml_path,
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
    )

    # 3. Rewrite frontmatter `domain:` field in every .md under domains/<new>/
    #    and candidates/<new>/*.
    pages = _rewrite_domain_field(
        _iter_markdown_pages(domains_new), old_n, new_n,
    )
    cands = 0
    if cands_new.exists():
        cands = _rewrite_domain_field(
            _iter_markdown_pages(cands_new), old_n, new_n,
        )

    # 4. app.yaml default_domain.
    from src.config import app_config_path, dump_app_config, load_app_config
    cfg = load_app_config(repo_root=repo_root)
    app_default_updated = False
    if str(cfg.get("default_domain") or "") == old_n:
        cfg["default_domain"] = new_n
        atomic_write(app_config_path(repo_root), dump_app_config(cfg))
        app_default_updated = True

    # 5. Agent config.yaml — update any `domain:` / `domains:` that name old_n.
    agents_updated: list[str] = []
    agents_dir = repo_root / "agents"
    if agents_dir.exists():
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            cfg_path = agent_dir / "config.yaml"
            if not cfg_path.exists():
                continue
            try:
                data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            changed = False
            if str(data.get("domain") or "") == old_n:
                data["domain"] = new_n
                changed = True
            domains = data.get("domains")
            if isinstance(domains, list):
                new_list = [new_n if str(d) == old_n else d for d in domains]
                if new_list != domains:
                    data["domains"] = new_list
                    changed = True
            if changed:
                atomic_write(
                    cfg_path,
                    yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
                )
                agents_updated.append(agent_dir.name)

    # 6. agents/*/seen.json — rewrite path-shaped IDs that embed the old name.
    seen_updated: list[str] = []
    if agents_dir.exists():
        old_prefix = f"domains/{old_n}/"
        new_prefix = f"domains/{new_n}/"
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            seen_path = agent_dir / "seen.json"
            if not seen_path.exists():
                continue
            try:
                data = json.loads(seen_path.read_text(encoding="utf-8") or "{}")
            except Exception:
                continue
            ids = data.get("seen") if isinstance(data, dict) else None
            if not isinstance(ids, list):
                continue
            rewritten = [s.replace(old_prefix, new_prefix) if isinstance(s, str) else s for s in ids]
            if rewritten != ids:
                data["seen"] = rewritten
                atomic_write(seen_path, json.dumps(data, indent=2))
                seen_updated.append(agent_dir.name)

    _append_audit(
        repo_root,
        f"rename-domain | {old_n} -> {new_n} | "
        f"pages={pages} candidates={cands} agents={len(agents_updated)}",
    )

    return RenameSummary(
        old=old_n, new=new_n,
        pages_updated=pages, candidates_updated=cands,
        agents_updated=agents_updated,
        app_default_updated=app_default_updated,
        seen_updated=seen_updated,
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


@dataclass
class DeleteSummary:
    domain: str
    domain_dir_removed: bool
    candidates_dir_removed: bool
    agents_cleared: list[str]
    app_default_fell_back_to: str | None


def delete_domain(
    name: str,
    confirm_1: str,
    confirm_2: str,
    repo_root: Path,
) -> DeleteSummary:
    """Remove a domain tree and its candidates. Requires typing the name twice.

    Refuses to delete the last remaining domain — the app needs at least one
    to function. Cascades: clears matching agent config.yaml ``domain`` /
    ``domains`` fields and falls the app-level ``default_domain`` back to
    the first surviving domain if the deleted one was it.
    """
    target = _normalise(name)
    c1 = _normalise(confirm_1)
    c2 = _normalise(confirm_2)
    if not target:
        raise DomainError("Domain name is required.")
    if target not in _list_domain_names(repo_root):
        raise DomainError(f"Domain '{target}' does not exist.")
    if c1 != target or c2 != target:
        raise DomainError(
            "Confirmation failed — both inputs must match the domain name "
            "exactly. Nothing was deleted.",
        )
    remaining = [d for d in _list_domain_names(repo_root) if d != target]
    if not remaining:
        raise DomainError(
            "Refusing to delete the last remaining domain — the app needs "
            "at least one. Create another domain first if you really mean to "
            "start over.",
        )

    domains_dir = repo_root / "domains" / target
    cands_dir = repo_root / "candidates" / target

    domain_removed = False
    if domains_dir.exists():
        shutil.rmtree(domains_dir)
        domain_removed = True

    cands_removed = False
    if cands_dir.exists():
        shutil.rmtree(cands_dir)
        cands_removed = True

    # Clear agent configs that pinned this domain so they don't crash on
    # the next scheduled run. We blank the field rather than guessing a
    # replacement — the user can repick in the Agents tab.
    agents_cleared: list[str] = []
    agents_dir = repo_root / "agents"
    if agents_dir.exists():
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            cfg_path = agent_dir / "config.yaml"
            if not cfg_path.exists():
                continue
            try:
                data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            changed = False
            if str(data.get("domain") or "") == target:
                data["domain"] = ""
                changed = True
            domains = data.get("domains")
            if isinstance(domains, list):
                new_list = [d for d in domains if str(d) != target]
                if new_list != domains:
                    data["domains"] = new_list
                    changed = True
            if changed:
                atomic_write(
                    cfg_path,
                    yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
                )
                agents_cleared.append(agent_dir.name)

    # default_domain fallback — re-point to the first survivor alphabetically.
    from src.config import app_config_path, dump_app_config, load_app_config
    cfg = load_app_config(repo_root=repo_root)
    new_default: str | None = None
    if str(cfg.get("default_domain") or "") == target:
        new_default = remaining[0]
        cfg["default_domain"] = new_default
        atomic_write(app_config_path(repo_root), dump_app_config(cfg))

    _append_audit(
        repo_root,
        f"delete-domain | {target} | agents_cleared={len(agents_cleared)} "
        f"default_fell_back_to={new_default or '-'}",
    )

    return DeleteSummary(
        domain=target,
        domain_dir_removed=domain_removed,
        candidates_dir_removed=cands_removed,
        agents_cleared=agents_cleared,
        app_default_fell_back_to=new_default,
    )


def _iter_markdown_pages(root: Path) -> Iterable[Path]:
    for md in root.rglob("*.md"):
        if md.is_file():
            yield md


def _rewrite_domain_field(paths: Iterable[Path], old: str, new: str) -> int:
    """Re-serialize frontmatter replacing ``domain: old`` with ``domain: new``.

    Skips files with no frontmatter (index.md, log.md, schema.md in most
    domains) — their content is non-structured markdown and doesn't carry
    a domain key.
    """
    changed = 0
    for path in paths:
        fm, body = parse_frontmatter(path)
        if not fm:
            continue
        if str(fm.get("domain") or "") != old:
            continue
        fm["domain"] = new
        content = (
            "---\n"
            + yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
            + "---\n\n"
            + body
        )
        atomic_write(path, content)
        changed += 1
    return changed


def _append_audit(repo_root: Path, line: str) -> None:
    log = repo_root / "audit" / "approvals.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] {line}\n")
