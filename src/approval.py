from datetime import date
from pathlib import Path
from typing import Optional
import yaml
from src.utils import now_iso, atomic_write
from src.validate import parse_frontmatter, check_path_traversal


def list_pending(domain: str, repo_root: Path = Path(".")) -> list[str]:
    pending_dir = repo_root / "candidates" / domain / "pending"
    if not pending_dir.exists():
        return []
    return sorted(p.name for p in pending_dir.glob("*.md"))


def approve_candidate(
    cand_filename: str,
    domain: str,
    reviewed_by: str = "user",
    repo_root: Path = Path("."),
) -> Path:
    """Approve a candidate page. Returns the approved page path."""
    cand_path = repo_root / "candidates" / domain / "pending" / cand_filename
    if not cand_path.exists():
        raise FileNotFoundError(f"Candidate not found: {cand_path}")

    fm, body = parse_frontmatter(cand_path)
    target_path_str = fm.get("target_path", "")

    if not target_path_str or not check_path_traversal(target_path_str, domain):
        raise ValueError(f"Invalid target_path: '{target_path_str}'")

    # Update frontmatter
    fm["status"] = "approved"
    fm["reviewed_by"] = reviewed_by
    fm["reviewed_at"] = now_iso()
    fm["origin_candidate_id"] = fm.get("candidate_id", "")
    # Remove candidate-only fields from approved page
    for field in ["candidate_id", "candidate_operation", "target_path", "raw_ids",
                  "duplicate_of", "possible_duplicates"]:
        fm.pop(field, None)

    new_content = "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False) + "---\n\n" + body

    target_path = repo_root / target_path_str
    target_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target_path, new_content)

    # Archive candidate
    archived_dir = repo_root / "candidates" / domain / "archived"
    archived_dir.mkdir(parents=True, exist_ok=True)
    cand_path.rename(archived_dir / cand_filename)

    # Update log
    _append_log(domain, "approve", fm.get("title", cand_filename), repo_root)

    # Audit log
    audit = repo_root / "audit" / "approvals.log"
    audit.parent.mkdir(parents=True, exist_ok=True)
    with open(audit, "a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] approve | {domain} | {cand_filename} → {target_path_str} | by={reviewed_by}\n")

    return target_path


def reject_candidate(
    cand_filename: str,
    domain: str,
    reason: str = "",
    repo_root: Path = Path("."),
) -> None:
    """Move a candidate to rejected/."""
    cand_path = repo_root / "candidates" / domain / "pending" / cand_filename
    if not cand_path.exists():
        raise FileNotFoundError(f"Candidate not found: {cand_path}")

    rejected_dir = repo_root / "candidates" / domain / "rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    cand_path.rename(rejected_dir / cand_filename)

    fm, _ = parse_frontmatter(rejected_dir / cand_filename)
    _append_log(domain, "reject", fm.get("title", cand_filename), repo_root)


def archive_candidate(
    cand_filename: str,
    domain: str,
    repo_root: Path = Path("."),
) -> None:
    """Move a candidate to archived/."""
    cand_path = repo_root / "candidates" / domain / "pending" / cand_filename
    if not cand_path.exists():
        raise FileNotFoundError(f"Candidate not found: {cand_path}")

    archived_dir = repo_root / "candidates" / domain / "archived"
    archived_dir.mkdir(parents=True, exist_ok=True)
    cand_path.rename(archived_dir / cand_filename)


def _append_log(domain: str, operation: str, title: str, repo_root: Path) -> None:
    log_path = repo_root / "domains" / domain / "log.md"
    if not log_path.exists():
        return
    today = date.today().isoformat()
    entry = f"\n## [{today}] {operation} | {title}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)
