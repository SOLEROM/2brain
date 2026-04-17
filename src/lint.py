import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from src.config import load_app_config
from src.utils import append_domain_log, atomic_write
from src.validate import parse_frontmatter


@dataclass
class LintReport:
    domain: str
    low_confidence_pages: list[dict] = field(default_factory=list)
    unresolved_contradictions: list[dict] = field(default_factory=list)
    orphans: list[dict] = field(default_factory=list)
    stale_pages: list[dict] = field(default_factory=list)
    stuck_jobs: list[dict] = field(default_factory=list)
    index_mismatches: list[dict] = field(default_factory=list)
    stale_candidates: list[dict] = field(default_factory=list)


def lint_domain(
    domain: str,
    repo_root: Path = Path("."),
    stale_days: Optional[int] = None,
    stuck_job_minutes: Optional[int] = None,
    low_confidence_threshold: Optional[float] = None,
) -> LintReport:
    app_cfg = load_app_config(repo_root=repo_root)
    lint_cfg = app_cfg.get("lint", {})
    if stale_days is None:
        stale_days = int(lint_cfg.get("stale_days", 90))
    if stuck_job_minutes is None:
        stuck_job_minutes = int(lint_cfg.get("stuck_job_minutes", 10))
    if low_confidence_threshold is None:
        low_confidence_threshold = float(lint_cfg.get("low_confidence_threshold", 0.35))

    report = LintReport(domain=domain)
    domain_dir = repo_root / "domains" / domain
    indexes_dir = domain_dir / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)

    approved_pages = _collect_approved_pages(domain_dir)
    page_texts: dict[Path, str] = {
        page: page.read_text(encoding="utf-8") for page in approved_pages
    }

    _scan_pages(report, approved_pages, page_texts, stale_days, low_confidence_threshold)
    _scan_orphans(report, approved_pages, page_texts)
    _scan_stuck_jobs(report, repo_root, stuck_job_minutes)
    _scan_index_mismatches(report, domain_dir, approved_pages)
    _scan_stale_candidates(report, repo_root, domain)

    _write_index(
        indexes_dir / "low-confidence.md",
        f"Low Confidence Pages — {report.domain}",
        [
            f"- [{p['title']}]({p['path']}) — confidence: {p['confidence']:.2f}"
            for p in report.low_confidence_pages
        ],
    )
    _write_index(
        indexes_dir / "contradictions.md",
        f"Unresolved Contradictions — {report.domain}",
        [f"- [{p['title']}]({p['path']})" for p in report.unresolved_contradictions],
    )
    _write_index(
        indexes_dir / "orphans.md",
        f"Orphaned Pages — {report.domain}",
        [f"- [{p['title']}]({p['path']})" for p in report.orphans],
    )
    _write_index(
        indexes_dir / "stale-pages.md",
        f"Stale Pages — {report.domain}",
        [
            f"- [{p['title']}]({p['path']}) — {p['days_old']} days old"
            for p in report.stale_pages
        ],
    )

    append_domain_log(
        repo_root, domain, "lint",
        f"{len(report.low_confidence_pages)} low-conf, "
        f"{len(report.unresolved_contradictions)} contradictions, "
        f"{len(report.orphans)} orphans, "
        f"{len(report.stale_pages)} stale, "
        f"{len(report.stuck_jobs)} stuck jobs",
    )
    return report


# ---------------------------------------------------------------------------
# Scanning helpers
# ---------------------------------------------------------------------------

def _collect_approved_pages(domain_dir: Path) -> list[Path]:
    pages: list[Path] = []
    for p in domain_dir.rglob("*.md"):
        if "indexes" in p.parts or ".archive" in p.parts:
            continue
        if p.name in ("index.md", "log.md", "schema.md"):
            continue
        pages.append(p)
    return pages


def _scan_pages(
    report: LintReport,
    pages: list[Path],
    page_texts: dict[Path, str],
    stale_days: int,
    low_confidence_threshold: float,
) -> None:
    for page in pages:
        fm, _ = parse_frontmatter(page)
        if not fm:
            continue
        title = fm.get("title", page.name)
        status = fm.get("status", "")
        confidence = float(fm.get("confidence", 1.0) or 1.0)
        text = page_texts[page]

        if confidence < low_confidence_threshold and status == "approved":
            report.low_confidence_pages.append({
                "title": title, "path": str(page), "confidence": confidence,
            })

        for match in re.finditer(
            r"\[!contradiction\](.*?)(?=\n>\s*\[!|\Z)", text, re.DOTALL,
        ):
            if re.search(r"status.*unresolved", match.group(0), re.IGNORECASE):
                report.unresolved_contradictions.append({"title": title, "path": str(page)})
                break

        days_old = _days_since(fm.get("updated_at", ""))
        if days_old is not None and status == "approved" and days_old > stale_days:
            report.stale_pages.append({
                "title": title, "path": str(page), "days_old": days_old,
            })


def _scan_orphans(
    report: LintReport,
    pages: list[Path],
    page_texts: dict[Path, str],
) -> None:
    all_text = "\n".join(page_texts.values())
    for page in pages:
        fm, _ = parse_frontmatter(page)
        title = fm.get("title", "")
        if not title:
            continue
        other_text = all_text.replace(page_texts[page], "", 1)
        if not re.search(rf"\[\[{re.escape(title)}\]\]", other_text):
            report.orphans.append({"title": title, "path": str(page)})


def _scan_stuck_jobs(report: LintReport, repo_root: Path, stuck_minutes: int) -> None:
    running_dir = repo_root / "jobs" / "running"
    if not running_dir.exists():
        return
    cutoff = datetime.now(timezone.utc).timestamp() - stuck_minutes * 60
    for job_file in running_dir.glob("*.yaml"):
        try:
            job = yaml.safe_load(job_file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        heartbeat = job.get("heartbeat_at", "")
        ts = _iso_to_epoch(heartbeat)
        if ts is None or ts < cutoff:
            report.stuck_jobs.append({
                "job_id": job.get("job_id", job_file.stem),
                "path": str(job_file),
                "heartbeat_at": heartbeat,
            })


def _scan_index_mismatches(
    report: LintReport, domain_dir: Path, approved_pages: list[Path],
) -> None:
    """Report pages referenced in index.md that don't exist (and vice versa)."""
    index_path = domain_dir / "index.md"
    if not index_path.exists():
        return
    index_text = index_path.read_text(encoding="utf-8")
    filenames = {p.name for p in approved_pages}
    # Markdown link paths like (domains/edge-ai/concepts/foo.md)
    referenced = set(re.findall(r"\(([^)]+\.md)\)", index_text))
    for ref in referenced:
        ref_name = Path(ref).name
        if ref_name not in filenames:
            report.index_mismatches.append({
                "kind": "missing_file", "reference": ref,
            })
    # Pages that exist but aren't referenced
    ref_names = {Path(r).name for r in referenced}
    for page in approved_pages:
        if page.name not in ref_names:
            report.index_mismatches.append({
                "kind": "not_indexed", "reference": str(page),
            })


def _scan_stale_candidates(report: LintReport, repo_root: Path, domain: str) -> None:
    """Flag candidates in pending/ older than max_candidate_age_days."""
    domain_yaml = repo_root / "domains" / domain / "domain.yaml"
    max_age_days = 90
    if domain_yaml.exists():
        try:
            cfg = yaml.safe_load(domain_yaml.read_text(encoding="utf-8")) or {}
            max_age_days = int(cfg.get("max_candidate_age_days", 90))
        except (yaml.YAMLError, ValueError):
            pass

    pending = repo_root / "candidates" / domain / "pending"
    if not pending.exists():
        return
    for cand in pending.glob("*.md"):
        fm, _ = parse_frontmatter(cand)
        days_old = _days_since(fm.get("created_at", ""))
        if days_old is not None and days_old > max_age_days:
            report.stale_candidates.append({
                "filename": cand.name, "path": str(cand), "days_old": days_old,
            })


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _days_since(iso_ts: str) -> Optional[int]:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_ts))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


def _iso_to_epoch(iso_ts: str) -> Optional[float]:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(str(iso_ts))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _write_index(path: Path, heading: str, lines: list[str]) -> None:
    body = [f"# {heading}\n", "> Auto-generated by lint. Do not edit manually.\n"]
    if lines:
        body.append("")
        body.extend(lines)
    else:
        body.append("")
        body.append("_None._")
    atomic_write(path, "\n".join(body) + "\n")
