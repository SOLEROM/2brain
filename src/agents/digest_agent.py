"""digestAgent — auto-digests new raw sources from `inbox/raw/` into
candidate pages for a configured domain.

Reads:  inbox/raw/<raw_id>/metadata.yaml (for domain_hint routing)
        agents/digestAgent/config.yaml  (domain, limits)
Writes: candidates/<domain>/pending/cand_<...>.md  (via src.digest.digest_raw)
        jobs/completed/job_<...>.yaml  (per inner digest + the wrapping agent-run)
        agents/digestAgent/seen.json  (raw_ids already processed, when scope=new)

Unlike deepSearch this agent does not consume `prompt.md` — the digest prompt
is built from the domain's `schema.md` by `src/digest.py`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml

from src.digest import digest_raw

if TYPE_CHECKING:
    from src.agents.registry import AgentMeta
    from src.agents.seen import SeenTracker


def _load_raw_metadata(raw_dir: Path) -> dict:
    meta_path = raw_dir / "metadata.yaml"
    if not meta_path.exists():
        return {}
    try:
        data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _list_raw_sources(repo_root: Path) -> list[tuple[str, dict]]:
    """Return (raw_id, metadata_dict) for every inbox/raw/<id>/ that has a source.md."""
    raw_root = repo_root / "inbox" / "raw"
    if not raw_root.exists():
        return []
    out: list[tuple[str, dict]] = []
    for child in sorted(raw_root.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        if not (child / "source.md").exists():
            continue
        out.append((child.name, _load_raw_metadata(child)))
    return out


def run_digest_agent(
    *,
    meta: "AgentMeta",
    repo_root: Path,
    job_id: str,
    question_override: Optional[str] = None,
    work_scope: str = "new",
    seen: Optional["SeenTracker"] = None,
    **_ignored,
) -> dict:
    """Execute one digestAgent run.

    For each eligible raw source under inbox/raw/, call digest_raw() and move the
    raw_id into the seen ledger on success. Fails fast if ANTHROPIC_API_KEY is
    missing so we don't generate N useless failed-digest jobs.
    """
    domain = str(meta.config.get("domain") or "").strip()
    if not domain:
        raise ValueError("digestAgent requires `domain` in config.yaml.")

    require_match = bool(meta.config.get("require_domain_hint_match", True))
    max_raws = int(meta.config.get("max_raws_per_run", 5))
    if max_raws < 1:
        max_raws = 1

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set — digestAgent cannot call Claude.")

    raws = _list_raw_sources(repo_root)
    total_discovered = len(raws)

    if require_match:
        raws = [
            (rid, m) for rid, m in raws
            if str(m.get("domain_hint") or "").strip() == domain
        ]

    if work_scope == "new" and seen is not None:
        raws = [(rid, m) for rid, m in raws if seen.is_new(rid)]

    eligible = len(raws)
    raws = raws[:max_raws]

    if not raws:
        msg = (
            f"Nothing to digest — discovered={total_discovered}, "
            f"matched-domain={eligible}, scope={work_scope}, domain={domain}."
        )
        return {
            "message": msg,
            "outputs": [],
            "domain": domain,
            "work_scope": work_scope,
            "skipped": True,
        }

    outputs: list[str] = []
    errors: list[str] = []
    for raw_id, _m in raws:
        try:
            produced = digest_raw(raw_id=raw_id, domain=domain, repo_root=repo_root)
        except Exception as exc:
            errors.append(f"{raw_id}: {type(exc).__name__}: {exc}")
            continue

        if produced:
            outputs.extend(produced)
            if seen is not None:
                seen.mark(raw_id)
        else:
            # digest_raw writes its own failed-job record; capture a brief note.
            errors.append(f"{raw_id}: digest produced no candidate (see jobs/failed/)")

    parts = [
        f"Digested {len(outputs)} candidate(s) from {len(raws)} raw source(s)",
        f"domain={domain}",
        f"scope={work_scope}",
    ]
    if eligible > max_raws:
        parts.append(f"capped {max_raws}/{eligible}")
    if errors:
        parts.append(f"{len(errors)} failed")
    message = " | ".join(parts)
    if errors:
        # Surface first few error strings in the message for quick inspection.
        message += " — " + "; ".join(errors[:3])

    return {
        "message": message,
        "outputs": outputs,
        "domain": domain,
        "work_scope": work_scope,
        "raws_discovered": total_discovered,
        "raws_eligible": eligible,
        "raws_processed": len(raws),
        "failures": errors,
    }
