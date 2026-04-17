"""Candidate approval, rejection, and archival.

Supports all candidate_operation values described in CLAUDE.md:
  create | update | replace | merge | archive | move | split
"""
import shutil
from pathlib import Path
from typing import Optional

import yaml

from src.utils import append_domain_log, append_line, atomic_write, now_iso
from src.validate import check_path_traversal, parse_frontmatter


# Operations where the raw source materialises into the approved tree — the
# only cases where dropping the raw source makes sense.
RAW_CONSUMING_OPERATIONS = {"create", "update", "replace", "merge"}


# Fields that only belong on candidate pages and must be stripped when approving.
CANDIDATE_ONLY_FIELDS = [
    "candidate_id",
    "candidate_operation",
    "target_path",
    "raw_ids",
    "duplicate_of",
    "possible_duplicates",
    "source_paths",
]


# ---------------------------------------------------------------------------
# Candidate listing
# ---------------------------------------------------------------------------

def list_pending(domain: str, repo_root: Path = Path(".")) -> list[str]:
    pending_dir = repo_root / "candidates" / domain / "pending"
    if not pending_dir.exists():
        return []
    # Skip partial candidates — they should not appear in the review queue.
    files = []
    for p in sorted(pending_dir.glob("*.md")):
        fm, _ = parse_frontmatter(p)
        if fm.get("status") == "partial":
            continue
        files.append(p.name)
    return files


# ---------------------------------------------------------------------------
# Main approval entry point
# ---------------------------------------------------------------------------

def approve_candidate(
    cand_filename: str,
    domain: str,
    reviewed_by: str = "user",
    repo_root: Path = Path("."),
    drop_raw: bool = False,
) -> Path:
    """Approve a candidate by running the operation its frontmatter declares.

    If `drop_raw` is True and the operation is raw-consuming (create, update,
    replace, or merge), also deletes each cited `raw_ids` folder from
    `inbox/raw/` — use when the reviewer doesn't want to keep the source.

    Returns the path of the resulting approved (or archived) page.
    """
    cand_path = _require_pending(cand_filename, domain, repo_root)
    fm, body = parse_frontmatter(cand_path)
    operation = (fm.get("candidate_operation") or "create").lower()

    if operation in ("create", "update", "replace"):
        result = _apply_write(
            cand_path, cand_filename, fm, body, domain, operation,
            reviewed_by, repo_root,
        )
    elif operation == "merge":
        result = _apply_merge(cand_path, cand_filename, fm, domain, repo_root)
    elif operation == "archive":
        result = _apply_archive(cand_path, cand_filename, fm, domain, repo_root)
    elif operation == "move":
        result = _apply_move(cand_path, cand_filename, fm, domain, repo_root)
    elif operation == "split":
        result = _apply_split(cand_path, cand_filename, fm, domain, repo_root)
    else:
        raise ValueError(f"Unknown candidate_operation: {operation!r}")

    if drop_raw and operation in RAW_CONSUMING_OPERATIONS:
        _drop_raw_sources(fm.get("raw_ids") or [], repo_root, cand_filename, domain)

    return result


def _drop_raw_sources(
    raw_ids: list,
    repo_root: Path,
    cand_filename: str,
    domain: str,
) -> None:
    """Delete each cited raw source folder. Missing ids are skipped silently."""
    for rid in raw_ids:
        if not rid or not isinstance(rid, str):
            continue
        # Guard against any path-separator shenanigans in the raw_id field.
        if "/" in rid or "\\" in rid or ".." in rid:
            continue
        raw_dir = repo_root / "inbox" / "raw" / rid
        if not raw_dir.is_dir():
            continue
        try:
            shutil.rmtree(raw_dir)
        except OSError:
            continue
        _audit(repo_root, f"drop-raw-on-approve | {domain} | {cand_filename} | {rid}")
        append_line(
            repo_root / "audit" / "ingest.log",
            f"[{now_iso()}] drop-raw-on-approve | {rid} | via={cand_filename}",
        )


# ---------------------------------------------------------------------------
# Rejection / archival of candidates (not approved pages)
# ---------------------------------------------------------------------------

def reject_candidate(
    cand_filename: str,
    domain: str,
    reason: str = "",
    reviewed_by: str = "user",
    repo_root: Path = Path("."),
) -> None:
    cand_path = _require_pending(cand_filename, domain, repo_root)
    rejected_dir = repo_root / "candidates" / domain / "rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    cand_path.rename(rejected_dir / cand_filename)

    fm, _ = parse_frontmatter(rejected_dir / cand_filename)
    title = fm.get("title", cand_filename)
    append_domain_log(repo_root, domain, "reject", title)
    _audit(
        repo_root,
        f"reject | {domain} | {cand_filename} | by={reviewed_by} | reason={reason}",
    )


def archive_candidate(
    cand_filename: str,
    domain: str,
    repo_root: Path = Path("."),
) -> None:
    cand_path = _require_pending(cand_filename, domain, repo_root)
    archived_dir = repo_root / "candidates" / domain / "archived"
    archived_dir.mkdir(parents=True, exist_ok=True)
    cand_path.rename(archived_dir / cand_filename)


# ---------------------------------------------------------------------------
# Operation handlers
# ---------------------------------------------------------------------------

def _apply_write(
    cand_path: Path,
    cand_filename: str,
    fm: dict,
    body: str,
    domain: str,
    operation: str,
    reviewed_by: str,
    repo_root: Path,
) -> Path:
    """create / update / replace: write candidate content to target_path."""
    target_path_str = fm.get("target_path", "")
    if not target_path_str or not check_path_traversal(target_path_str, domain):
        raise ValueError(f"Invalid target_path: '{target_path_str}'")

    fm_out = dict(fm)
    fm_out["status"] = "approved"
    fm_out["reviewed_by"] = reviewed_by
    fm_out["reviewed_at"] = now_iso()
    fm_out["updated_at"] = now_iso()
    if fm.get("candidate_id"):
        fm_out["origin_candidate_id"] = fm["candidate_id"]
    for field in CANDIDATE_ONLY_FIELDS:
        fm_out.pop(field, None)

    content = _render_page(fm_out, body)
    target_path = repo_root / target_path_str
    atomic_write(target_path, content)

    _archive_candidate_file(cand_path, cand_filename, domain, repo_root)
    append_domain_log(
        repo_root, domain, "approve",
        f"{fm_out.get('title', cand_filename)} ({operation})",
    )
    _audit(
        repo_root,
        f"approve {operation} | {domain} | {cand_filename} → {target_path_str} | by={reviewed_by}",
    )
    return target_path


def _apply_merge(
    cand_path: Path,
    cand_filename: str,
    fm: dict,
    domain: str,
    repo_root: Path,
) -> Path:
    """merge: reviewer edits the target page directly; we just archive the candidate."""
    target_path_str = fm.get("target_path", "")
    if not target_path_str or not check_path_traversal(target_path_str, domain):
        raise ValueError(f"Invalid target_path: '{target_path_str}'")
    target_path = repo_root / target_path_str
    _archive_candidate_file(cand_path, cand_filename, domain, repo_root)
    append_domain_log(
        repo_root, domain, "merge",
        f"{fm.get('title', cand_filename)} → {target_path_str}",
    )
    _audit(repo_root, f"merge | {domain} | {cand_filename} → {target_path_str}")
    return target_path


def _apply_archive(
    cand_path: Path,
    cand_filename: str,
    fm: dict,
    domain: str,
    repo_root: Path,
) -> Path:
    """archive: move target approved page to .archive/."""
    target_path_str = fm.get("target_path", "")
    if not target_path_str or not check_path_traversal(target_path_str, domain):
        raise ValueError(f"Invalid target_path: '{target_path_str}'")
    target_path = repo_root / target_path_str
    if not target_path.exists():
        raise FileNotFoundError(f"Approved page not found: {target_path_str}")

    archive_dir = repo_root / "domains" / domain / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_path = archive_dir / target_path.name

    existing_fm, existing_body = parse_frontmatter(target_path)
    existing_fm["status"] = "archived"
    archived_content = _render_page(existing_fm, existing_body)
    atomic_write(archived_path, archived_content)
    target_path.unlink()

    _archive_candidate_file(cand_path, cand_filename, domain, repo_root)
    append_domain_log(repo_root, domain, "archive", fm.get("title", cand_filename))
    _audit(repo_root, f"archive | {domain} | {target_path_str}")
    return archived_path


def _apply_move(
    cand_path: Path,
    cand_filename: str,
    fm: dict,
    domain: str,
    repo_root: Path,
) -> Path:
    """move: relocate approved page to new target_path (may cross domains)."""
    target_path_str = fm.get("target_path", "")
    source_paths = fm.get("source_paths") or []
    if not source_paths:
        raise ValueError("move operation requires source_paths")
    source_str = source_paths[0]
    if not check_path_traversal(source_str, domain):
        raise ValueError(f"Invalid source path: {source_str}")
    # target_path may be in a different domain for move — only require it's under domains/
    tgt = Path(target_path_str)
    if len(tgt.parts) < 2 or tgt.parts[0] != "domains":
        raise ValueError(f"Invalid target_path for move: {target_path_str}")

    src_full = repo_root / source_str
    tgt_full = repo_root / target_path_str
    if not src_full.exists():
        raise FileNotFoundError(f"Source page not found: {source_str}")
    tgt_full.parent.mkdir(parents=True, exist_ok=True)
    src_full.rename(tgt_full)

    _archive_candidate_file(cand_path, cand_filename, domain, repo_root)
    append_domain_log(
        repo_root, domain, "move",
        f"{fm.get('title', cand_filename)}: {source_str} → {target_path_str}",
    )
    _audit(repo_root, f"move | {domain} | {source_str} → {target_path_str}")
    return tgt_full


def _apply_split(
    cand_path: Path,
    cand_filename: str,
    fm: dict,
    domain: str,
    repo_root: Path,
) -> Path:
    """split: archive the split proposal; reviewer follows up with separate approvals."""
    _archive_candidate_file(cand_path, cand_filename, domain, repo_root)
    append_domain_log(
        repo_root, domain, "split",
        f"{fm.get('title', cand_filename)} (proposal archived)",
    )
    _audit(repo_root, f"split | {domain} | {cand_filename}")
    return repo_root / "candidates" / domain / "archived" / cand_filename


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _require_pending(cand_filename: str, domain: str, repo_root: Path) -> Path:
    cand_path = repo_root / "candidates" / domain / "pending" / cand_filename
    if not cand_path.exists():
        raise FileNotFoundError(f"Candidate not found: {cand_path}")
    return cand_path


def _archive_candidate_file(
    cand_path: Path, cand_filename: str, domain: str, repo_root: Path,
) -> None:
    archived_dir = repo_root / "candidates" / domain / "archived"
    archived_dir.mkdir(parents=True, exist_ok=True)
    cand_path.rename(archived_dir / cand_filename)


def _render_page(fm: dict, body: str) -> str:
    return (
        "---\n"
        + yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
        + "---\n\n"
        + body
    )


def _audit(repo_root: Path, detail: str) -> None:
    append_line(repo_root / "audit" / "approvals.log", f"[{now_iso()}] {detail}")
