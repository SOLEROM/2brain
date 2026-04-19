"""wikiGraph — builds the connection graph across approved pages in a domain.

Deterministic (no LLM): scans every approved page and extracts three edge
types, then writes ``domains/<domain>/indexes/connections.json``.

Edge sources:
  - wikilink      — ``[[Page Title]]`` occurrences in page body, resolved by
                    title match (case-insensitive, whitespace-normalised).
  - related       — entries in frontmatter ``related_pages``.
  - shared-source — pages that cite the same ``raw_id`` in their ``sources``
                    list. Skips raw_ids cited by more than MAX_CITERS_PER_RAW
                    pages to avoid N² blow-up from a popular source.

work_scope is accepted to conform to the runner interface but ignored: every
run re-computes the full map (the graph is a global property).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.utils import atomic_write, now_iso
from src.validate import parse_frontmatter

if TYPE_CHECKING:
    from src.agents.registry import AgentMeta
    from src.agents.seen import SeenTracker


WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
SKIP_FILES = {"index.md", "log.md", "schema.md"}
SKIP_PARTS = {"indexes", ".archive"}
MAX_CITERS_PER_RAW = 10


def _resolve_domains(meta: "AgentMeta", repo_root: Path) -> list[str]:
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


def _iter_approved_pages(domain_dir: Path):
    for md_file in sorted(domain_dir.rglob("*.md")):
        if any(seg in SKIP_PARTS for seg in md_file.parts):
            continue
        if md_file.name in SKIP_FILES:
            continue
        yield md_file


def _norm_title(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _build_graph(domain: str, repo_root: Path) -> dict:
    domain_dir = repo_root / "domains" / domain
    nodes: list[dict] = []
    title_to_id: dict[str, str] = {}
    bodies: dict[str, str] = {}
    frontmatters: dict[str, dict] = {}

    if not domain_dir.exists():
        return {"nodes": [], "edges": [], "stats": {}, "broken_wikilinks": []}

    for page in _iter_approved_pages(domain_dir):
        fm, body = parse_frontmatter(page)
        title = str(fm.get("title") or "").strip()
        if not title:
            continue
        rel = page.relative_to(repo_root).as_posix()
        conf = float(fm.get("confidence", 0.0) or 0.0)
        tags = [str(t) for t in (fm.get("tags") or [])]
        nodes.append({
            "id": rel,
            "title": title,
            "type": str(fm.get("type") or ""),
            "confidence": conf,
            "tags": tags,
            "status": str(fm.get("status") or ""),
            "updated_at": str(fm.get("updated_at") or ""),
        })
        title_to_id[_norm_title(title)] = rel
        bodies[rel] = body
        frontmatters[rel] = fm

    edges: list[dict] = []
    broken: list[dict] = []

    # wikilink edges (directed, A → B, weight = occurrence count)
    for src_rel, body in bodies.items():
        counts: dict[str, int] = defaultdict(int)
        for m in WIKILINK_RE.finditer(body):
            target = _norm_title(m.group(1))
            dst = title_to_id.get(target)
            if dst is None:
                broken.append({"src": src_rel, "target": m.group(1).strip()})
                continue
            if dst == src_rel:
                continue
            counts[dst] += 1
        for dst, w in counts.items():
            edges.append({
                "src": src_rel, "dst": dst,
                "type": "wikilink", "weight": w, "directed": True,
            })

    # related_pages edges (directed, weight 1)
    for src_rel, fm in frontmatters.items():
        related = fm.get("related_pages") or []
        if not isinstance(related, list):
            continue
        for entry in related:
            target = _norm_title(str(entry))
            dst = title_to_id.get(target)
            if dst is None or dst == src_rel:
                continue
            edges.append({
                "src": src_rel, "dst": dst,
                "type": "related", "weight": 1, "directed": True,
            })

    # shared-source edges (undirected, canonical order, weight = shared raws)
    raw_to_pages: dict[str, list[str]] = defaultdict(list)
    for src_rel, fm in frontmatters.items():
        sources = fm.get("sources") or []
        if not isinstance(sources, list):
            continue
        for s in sources:
            raw_id = None
            if isinstance(s, dict):
                raw_id = s.get("raw_id") or s.get("id")
            elif isinstance(s, str):
                raw_id = s
            if raw_id:
                raw_to_pages[str(raw_id)].append(src_rel)

    pair_weights: dict[tuple[str, str], int] = defaultdict(int)
    for citers in raw_to_pages.values():
        uniq = sorted(set(citers))
        if len(uniq) < 2 or len(uniq) > MAX_CITERS_PER_RAW:
            continue
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                pair_weights[(uniq[i], uniq[j])] += 1
    for (a, b), w in pair_weights.items():
        edges.append({
            "src": a, "dst": b,
            "type": "shared-source", "weight": w, "directed": False,
        })

    stats = {
        "nodes": len(nodes),
        "edges": len(edges),
        "wikilink_edges": sum(1 for e in edges if e["type"] == "wikilink"),
        "related_edges": sum(1 for e in edges if e["type"] == "related"),
        "shared_source_edges": sum(1 for e in edges if e["type"] == "shared-source"),
        "broken_wikilinks": len(broken),
    }
    return {"nodes": nodes, "edges": edges, "stats": stats, "broken_wikilinks": broken}


def _write_connections(repo_root: Path, domain: str, graph: dict) -> str:
    payload = {
        "generated_at": now_iso(),
        "generated_by": "wikiGraph",
        "domain": domain,
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "stats": graph["stats"],
        "broken_wikilinks": graph["broken_wikilinks"],
    }
    out = repo_root / "domains" / domain / "indexes" / "connections.json"
    atomic_write(out, json.dumps(payload, indent=2, ensure_ascii=False))
    return out.relative_to(repo_root).as_posix()


def run_wiki_graph(
    *,
    meta: "AgentMeta",
    repo_root: Path,
    job_id: str,
    question_override: Optional[str] = None,
    work_scope: str = "all",
    seen: Optional["SeenTracker"] = None,
    **_ignored,
) -> dict:
    domains = _resolve_domains(meta, repo_root)
    if not domains:
        return {
            "message": "No domains configured and none found under domains/.",
            "outputs": [],
            "skipped": True,
        }

    outputs: list[str] = []
    per_domain: list[dict] = []
    errors: list[str] = []

    for domain in domains:
        try:
            graph = _build_graph(domain, repo_root)
            rel = _write_connections(repo_root, domain, graph)
            outputs.append(rel)
            per_domain.append({"domain": domain, **graph["stats"]})
        except Exception as exc:
            errors.append(f"{domain}: {type(exc).__name__}: {exc}")

    totals = {
        "nodes": sum(d.get("nodes", 0) for d in per_domain),
        "edges": sum(d.get("edges", 0) for d in per_domain),
        "broken": sum(d.get("broken_wikilinks", 0) for d in per_domain),
    }
    parts = [f"Mapped {len(per_domain)} domain(s)"]
    parts.append(
        f"nodes={totals['nodes']} | edges={totals['edges']} | "
        f"broken-wikilinks={totals['broken']}"
    )
    if errors:
        parts.append(f"{len(errors)} failed")
    message = " — ".join(parts)
    if errors:
        message += " — " + "; ".join(errors[:3])

    return {
        "message": message,
        "outputs": outputs,
        "domains": [d["domain"] for d in per_domain],
        "per_domain": per_domain,
        "failures": errors,
    }
