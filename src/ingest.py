import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import yaml
from src.utils import slug_from_title, hash8, now_iso, atomic_write


def build_raw_id(title: str, url_or_content: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = slug_from_title(title)[:40]
    h = hash8(url_or_content)
    return f"raw_{ts}_{slug}_{h}"


def sanitize_content(content: str) -> str:
    """Strip any leading YAML frontmatter delimiters from raw content."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].lstrip("\n")
    return content


def ingest_source(
    content: str,
    title: str,
    source_type: str = "text",
    url: Optional[str] = None,
    domain_hint: Optional[str] = None,
    submitted_by: str = "user",
    repo_root: Path = Path("."),
) -> str:
    """Ingest a raw source. Returns raw_id."""
    url_or_content = url or content
    raw_id = build_raw_id(title, url_or_content)
    raw_dir = repo_root / "inbox" / "raw" / raw_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "assets").mkdir(exist_ok=True)

    safe_content = sanitize_content(content)
    atomic_write(raw_dir / "source.md", safe_content)

    content_hash = hashlib.sha256(content.encode()).hexdigest()
    metadata = {
        "id": raw_id,
        "title": title,
        "source_type": source_type,
        "origin": "manual",
        "url": url,
        "submitted_by": submitted_by,
        "ingested_at": now_iso(),
        "content_hash": content_hash,
        "domain_hint": domain_hint,
        "tags": [],
        "license": None,
        "fetch_status": "ok",
    }
    atomic_write(raw_dir / "metadata.yaml", yaml.dump(metadata, allow_unicode=True))

    # Audit log
    audit_log = repo_root / "audit" / "ingest.log"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    entry = f"[{now_iso()}] ingest | {title} | {raw_id} | domain_hint={domain_hint}\n"
    with open(audit_log, "a", encoding="utf-8") as f:
        f.write(entry)

    return raw_id
