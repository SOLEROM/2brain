import os
import re
import tempfile
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

import yaml
import anthropic

from src.utils import slug_from_title, hash8, now_iso, atomic_write
from src.validate import validate_frontmatter, parse_frontmatter, check_path_traversal
from src.config import load_agents_config


# ---------------------------------------------------------------------------
# Candidate ID helpers
# ---------------------------------------------------------------------------

def build_candidate_id(title: str, content: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = slug_from_title(title)[:40]
    h = hash8(content)
    return f"cand_{ts}_{slug}_{h}.md"


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------

def find_near_duplicates(title: str, domain: str, repo_root: Path) -> list[str]:
    """Return paths of pages with titles similar to the given title."""
    slug = slug_from_title(title)
    title_words = set(slug.split("-"))
    matches: list[str] = []

    for search_dir in [
        repo_root / "domains" / domain,
        repo_root / "candidates" / domain / "pending",
    ]:
        if not search_dir.exists():
            continue
        for md_file in search_dir.rglob("*.md"):
            fm, _ = parse_frontmatter(md_file)
            existing_title = fm.get("title")
            if not existing_title:
                continue
            existing_slug = slug_from_title(existing_title)
            existing_words = set(existing_slug.split("-"))
            overlap = title_words & existing_words
            if len(overlap) >= max(2, len(title_words) * 0.6):
                matches.append(str(md_file))

    return matches


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_digest_prompt(
    raw_content: str,
    raw_id: str,
    domain: str,
    repo_root: Path,
) -> str:
    schema_path = repo_root / "domains" / domain / "schema.md"
    schema = schema_path.read_text(encoding="utf-8") if schema_path.exists() else "(no schema found)"

    return f"""You are a knowledge wiki digest agent. Your task is to read a raw source and produce one Markdown candidate page.

## Domain Schema
{schema}

## Raw Source ID
{raw_id}

## Raw Source Content
{raw_content}

## Instructions
1. Produce exactly ONE complete Markdown candidate page.
2. The page MUST start with a YAML frontmatter block delimited by --- lines.
3. Required frontmatter fields: title, domain, type, status, confidence, sources, created_at, updated_at, tags, candidate_id, candidate_operation, target_path, raw_ids.
4. Set status: candidate
5. Set candidate_operation: create (or update if this is a revision of an existing page)
6. Set target_path to the appropriate path under domains/{domain}/
7. Every claim in "## Key Claims" must include Evidence and Evidence type lines.
8. Use confidence score between 0.0 and 1.0 following the rubric.
9. Do NOT include broken wikilinks. List missing pages in ## Suggested New Pages instead.
10. Output ONLY the Markdown page. No explanation or preamble.

Current timestamp: {now_iso()}
Domain: {domain}
"""


# ---------------------------------------------------------------------------
# Frontmatter parsing from string (not file)
# ---------------------------------------------------------------------------

def parse_frontmatter_str(text: str) -> tuple[dict, str]:
    """Parse frontmatter from a string. Returns (frontmatter_dict, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, parts[2].lstrip("\n")


# ---------------------------------------------------------------------------
# Candidate file writer
# ---------------------------------------------------------------------------

def write_candidate(page_content: str, domain: str, repo_root: Path) -> str:
    """Write a candidate page to pending/. Returns the candidate filename."""
    fm, _ = parse_frontmatter_str(page_content)
    title = fm.get("title", "untitled")
    cand_filename = build_candidate_id(title, page_content)

    pending_dir = repo_root / "candidates" / domain / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(pending_dir / cand_filename, page_content)
    return cand_filename


# ---------------------------------------------------------------------------
# Main digest entry point
# ---------------------------------------------------------------------------

def digest_raw(
    raw_id: str,
    domain: str,
    repo_root: Path = Path("."),
    api_key: Optional[str] = None,
) -> list[str]:
    """Digest a raw source into candidate pages. Returns list of candidate filenames."""
    raw_dir = repo_root / "inbox" / "raw" / raw_id
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw source not found: {raw_id}")

    source_content = (raw_dir / "source.md").read_text(encoding="utf-8")

    # Load agent config — resolve relative path against repo_root so tests work
    agents_cfg_path = repo_root / "config" / "agents.yaml"
    if agents_cfg_path.exists():
        cfg = load_agents_config(agents_cfg_path)
    else:
        cfg = load_agents_config()  # fallback to cwd-relative

    model = cfg["digest_agent"]["model"]

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    prompt = build_digest_prompt(source_content, raw_id, domain, repo_root)

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    page_text = message.content[0].text.strip()

    # Validate frontmatter before writing
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tf:
        tf.write(page_text)
        tf_path = tf.name

    try:
        result = validate_frontmatter(Path(tf_path))
    finally:
        os.unlink(tf_path)

    if not result.valid:
        _write_failed_job(raw_id, domain, result.errors, repo_root)
        return []

    # Security: validate target_path is within the domain
    fm, _ = parse_frontmatter_str(page_text)
    target_path = fm.get("target_path", "")
    if target_path and not check_path_traversal(target_path, domain):
        _write_failed_job(raw_id, domain, [f"Invalid target_path: {target_path}"], repo_root)
        return []

    cand_filename = write_candidate(page_text, domain, repo_root)
    _write_completed_job(raw_id, domain, [cand_filename], repo_root)
    _append_domain_log(domain, raw_id, cand_filename, repo_root)

    return [cand_filename]


# ---------------------------------------------------------------------------
# Job record helpers
# ---------------------------------------------------------------------------

def _write_failed_job(raw_id: str, domain: str, errors: list[str], repo_root: Path) -> None:
    h = hash8(raw_id)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    job_id = f"job_{ts}_digest_{h}"
    job = {
        "job_id": job_id,
        "job_type": "digest",
        "domain": domain,
        "status": "failed",
        "created_at": now_iso(),
        "input": raw_id,
        "outputs": [],
        "agent": "digest-agent",
        "error": "; ".join(errors),
    }
    failed_dir = repo_root / "jobs" / "failed"
    failed_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(failed_dir / f"{job_id}.yaml", yaml.dump(job, allow_unicode=True))


def _write_completed_job(raw_id: str, domain: str, outputs: list[str], repo_root: Path) -> None:
    h = hash8(raw_id)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    job_id = f"job_{ts}_digest_{h}"
    job = {
        "job_id": job_id,
        "job_type": "digest",
        "domain": domain,
        "status": "completed",
        "created_at": now_iso(),
        "completed_at": now_iso(),
        "input": raw_id,
        "outputs": outputs,
        "agent": "digest-agent",
    }
    completed_dir = repo_root / "jobs" / "completed"
    completed_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(completed_dir / f"{job_id}.yaml", yaml.dump(job, allow_unicode=True))


def _append_domain_log(domain: str, raw_id: str, cand_filename: str, repo_root: Path) -> None:
    log_path = repo_root / "domains" / domain / "log.md"
    if not log_path.exists():
        return
    today = date.today().isoformat()
    entry = f"\n## [{today}] digest | {raw_id} → {cand_filename}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)
