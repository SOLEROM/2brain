from dataclasses import dataclass, field
from pathlib import Path
from src.validate import parse_frontmatter


@dataclass
class PageMatch:
    title: str
    path: str
    status: str
    confidence: float
    domain: str
    type: str
    tags: list
    snippet: str = ""


def confidence_label(score: float) -> str:
    if score >= 0.90:
        return "Very high"
    if score >= 0.75:
        return "High"
    if score >= 0.55:
        return "Medium"
    if score >= 0.35:
        return "Low"
    return "Very low"


def _load_pages(domain: str, repo_root: Path) -> list[tuple]:
    """Load all approved and candidate pages. Returns (path, frontmatter, body) tuples."""
    pages = []
    for search_dir in [
        repo_root / "domains" / domain,
        repo_root / "candidates" / domain / "pending",
    ]:
        if not search_dir.exists():
            continue
        for md_file in search_dir.rglob("*.md"):
            fm, body = parse_frontmatter(md_file)
            if fm.get("title"):
                pages.append((md_file, fm, body))
    return pages


def search_pages(
    query: str,
    domain: str,
    repo_root: Path = Path("."),
    include_candidates: bool = True,
) -> list[PageMatch]:
    """Search pages by keyword. Returns ranked PageMatch list."""
    pages = _load_pages(domain, repo_root)
    query_lower = query.lower().strip()
    results = []

    for path, fm, body in pages:
        status = fm.get("status", "unknown")
        if status == "candidate" and not include_candidates:
            continue
        if status not in ("approved", "candidate"):
            continue

        # Score based on keyword hits
        score = 0
        title = fm.get("title", "")
        tags = fm.get("tags", []) or []
        content = title + " " + " ".join(str(t) for t in tags) + " " + body

        if not query_lower:
            score = 1
        else:
            for word in query_lower.split():
                if word in content.lower():
                    score += 1
                if word in title.lower():
                    score += 2

        if score == 0:
            continue

        snippet = _extract_snippet(body, query_lower)
        results.append(PageMatch(
            title=title,
            path=str(path),
            status=status,
            confidence=float(fm.get("confidence", 0.0)),
            domain=fm.get("domain", domain),
            type=fm.get("type", "unknown"),
            tags=[str(t) for t in tags],
            snippet=snippet,
        ))

    results.sort(key=lambda r: (r.status == "approved", r.confidence), reverse=True)
    return results


def _extract_snippet(body: str, query: str, context: int = 100) -> str:
    if not query:
        return body[:200].strip()
    words = query.split()
    if not words:
        return body[:200].strip()
    idx = body.lower().find(words[0])
    if idx == -1:
        return body[:200].strip()
    start = max(0, idx - context // 2)
    end = min(len(body), idx + context // 2)
    return "..." + body[start:end].strip() + "..."
