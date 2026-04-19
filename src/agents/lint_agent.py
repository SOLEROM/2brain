"""lintAgent — scheduled health check for one or more domains.

Reads:  agents/lintAgent/config.yaml  (domain | domains list; optional lint thresholds)
Writes: domains/<domain>/indexes/{low-confidence,contradictions,orphans,stale-pages}.md
        domains/<domain>/log.md  (append-only lint entry, via lint_domain)
        jobs/completed/job_<...>.yaml  (agent-run record, via runner)

lint is deterministic — no LLM call, no API key required. work_scope is
accepted to conform to the runner interface but is ignored: every run
re-scans the full domain tree.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.lint import lint_domain

if TYPE_CHECKING:
    from src.agents.registry import AgentMeta
    from src.agents.seen import SeenTracker


def _resolve_domains(meta: "AgentMeta", repo_root: Path) -> list[str]:
    """domains list wins over single domain; fall back to all domain folders."""
    listed = meta.config.get("domains")
    if isinstance(listed, list) and listed:
        return [str(d).strip() for d in listed if str(d).strip()]

    single = str(meta.config.get("domain") or "").strip()
    if single:
        return [single]

    domains_root = repo_root / "domains"
    if not domains_root.exists():
        return []
    return sorted(
        child.name for child in domains_root.iterdir() if child.is_dir()
    )


def run_lint_agent(
    *,
    meta: "AgentMeta",
    repo_root: Path,
    job_id: str,
    question_override: Optional[str] = None,
    work_scope: str = "all",
    seen: Optional["SeenTracker"] = None,
    **_ignored,
) -> dict:
    """Run lint_domain() across the configured domain(s)."""
    domains = _resolve_domains(meta, repo_root)
    if not domains:
        return {
            "message": "No domains configured and none found under domains/.",
            "outputs": [],
            "skipped": True,
        }

    stale_days = meta.config.get("stale_days")
    stuck_minutes = meta.config.get("stuck_job_minutes")
    low_conf = meta.config.get("low_confidence_threshold")

    per_domain: list[dict] = []
    errors: list[str] = []
    for domain in domains:
        try:
            report = lint_domain(
                domain,
                repo_root=repo_root,
                stale_days=int(stale_days) if stale_days is not None else None,
                stuck_job_minutes=int(stuck_minutes) if stuck_minutes is not None else None,
                low_confidence_threshold=float(low_conf) if low_conf is not None else None,
            )
        except Exception as exc:
            errors.append(f"{domain}: {type(exc).__name__}: {exc}")
            continue
        per_domain.append({
            "domain": domain,
            "low_confidence": len(report.low_confidence_pages),
            "contradictions": len(report.unresolved_contradictions),
            "orphans": len(report.orphans),
            "stale_pages": len(report.stale_pages),
            "stuck_jobs": len(report.stuck_jobs),
            "index_mismatches": len(report.index_mismatches),
            "stale_candidates": len(report.stale_candidates),
        })

    parts = [f"Linted {len(per_domain)} domain(s)"]
    totals = {
        "low-conf": sum(d["low_confidence"] for d in per_domain),
        "contradictions": sum(d["contradictions"] for d in per_domain),
        "orphans": sum(d["orphans"] for d in per_domain),
        "stale": sum(d["stale_pages"] for d in per_domain),
        "stuck": sum(d["stuck_jobs"] for d in per_domain),
    }
    parts.append(
        f"low-conf={totals['low-conf']} | "
        f"contradictions={totals['contradictions']} | "
        f"orphans={totals['orphans']} | "
        f"stale={totals['stale']} | "
        f"stuck={totals['stuck']}"
    )
    if errors:
        parts.append(f"{len(errors)} failed")
    message = " — ".join(parts)
    if errors:
        message += " — " + "; ".join(errors[:3])

    # Outputs = the regenerated index files so the Jobs tab can link them.
    outputs: list[str] = []
    for d in per_domain:
        base = f"domains/{d['domain']}/indexes"
        outputs.extend([
            f"{base}/low-confidence.md",
            f"{base}/contradictions.md",
            f"{base}/orphans.md",
            f"{base}/stale-pages.md",
        ])

    return {
        "message": message,
        "outputs": outputs,
        "domains": [d["domain"] for d in per_domain],
        "per_domain": per_domain,
        "failures": errors,
    }
