import json
import os
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
import anthropic

from src.utils import (
    append_domain_log,
    atomic_write,
    coerce_datetimes,
    hash8,
    now_iso,
    slug_from_title,
)
from src.validate import check_path_traversal, parse_frontmatter, validate_frontmatter
from src.config import load_agents_config, load_app_config


# Fallbacks used when config/app.yaml is missing or partial.
MAX_SOURCE_CHARS = 40_000
DIGEST_MAX_TOKENS = 4096


# Event callback: receives dicts describing each digest step.
# Each dict has keys: ts, level ('info'|'warn'|'error'|'done'), step, message,
# and may include extra keys like `candidate`, `traceback`, `target_path`.
EventCb = Optional[Callable[[dict], None]]


def _emit(cb: EventCb, level: str, step: str, message: str, **extra: Any) -> None:
    if cb is None:
        return
    evt = {"ts": now_iso(), "level": level, "step": step, "message": message}
    evt.update(extra)
    try:
        cb(evt)
    except Exception:
        pass


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

def extract_page_from_response(text: str) -> str:
    """Strip any preamble Claude may have added before the --- frontmatter block."""
    idx = text.find("---")
    if idx == -1:
        return text
    return text[idx:]


def parse_frontmatter_str(text: str) -> tuple[dict, str]:
    """Parse frontmatter from a string. Returns (frontmatter_dict, body).

    datetime/date values are coerced to ISO strings, matching parse_frontmatter.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        fm = {}
    return coerce_datetimes(fm), parts[2].lstrip("\n")


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
    on_event: EventCb = None,
) -> list[str]:
    """Digest a raw source into candidate pages. Returns list of candidate filenames.

    Pass `on_event` to receive a dict per step (ts, level, step, message). The
    callback is invoked synchronously from this function's thread. Exceptions
    raised inside the callback are swallowed so they never abort the digest.

    On validation failure, writes a failed job record to jobs/failed/ and returns [].
    """
    # Set up job identity eagerly so any early failure still persists a report.
    job_id = _build_job_id(raw_id)
    created_at = now_iso()
    started_at = now_iso()

    # Publish a running record immediately so the digest tab (and anyone else)
    # can attach to this job's live event stream.
    _write_running_record(repo_root, job_id, domain, raw_id, created_at, started_at)

    # Tee every event three ways:
    #   1. into `events` (kept locally in case we need it)
    #   2. appended to jobs/running/<id>.events.jsonl for live observers
    #   3. forwarded to the caller's on_event (for SSE pushers, tests, CLI)
    events: list[dict] = []
    _user_cb = on_event

    def _tee(evt: dict) -> None:
        events.append(evt)
        _append_event(repo_root, job_id, evt)
        if _user_cb is not None:
            try:
                _user_cb(evt)
            except Exception:
                pass

    on_event = _tee

    def _base_job() -> dict:
        return {
            "job_id": job_id,
            "job_type": "digest",
            "domain": domain,
            "created_at": created_at,
            "started_at": started_at,
            "heartbeat_at": now_iso(),
            "completed_at": now_iso(),
            "input": raw_id,
            "outputs": [],
            "agent": "digest-agent",
        }

    def _finalize_failed(err_msg: str) -> list[str]:
        final = _base_job()
        final["status"] = "failed"
        final["error"] = err_msg
        _finalize_running(repo_root, job_id, "failed", final)
        return []

    _emit(on_event, "info", "start",
          f"Starting digest of {raw_id} → {domain}",
          raw_id=raw_id, domain=domain)

    raw_dir = repo_root / "inbox" / "raw" / raw_id
    if not raw_dir.exists():
        err = f"Raw source not found: {raw_id}"
        _emit(on_event, "error", "lookup", err)
        return _finalize_failed(err)

    source_path = raw_dir / "source.md"
    if not source_path.exists():
        err = f"source.md missing in {raw_dir}"
        _emit(on_event, "error", "lookup", err)
        return _finalize_failed(err)
    try:
        source_content = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        _emit(on_event, "error", "load-source",
              f"Could not read source.md: {exc}",
              traceback=traceback.format_exc())
        return _finalize_failed(f"Could not read source.md: {exc}")
    _emit(on_event, "info", "load-source",
          f"Loaded source.md ({len(source_content):,} chars)")

    app_cfg = load_app_config(repo_root=repo_root)
    max_chars = int(app_cfg.get("digest", {}).get("max_source_chars", MAX_SOURCE_CHARS))
    max_tokens = int(app_cfg.get("digest", {}).get("max_tokens", DIGEST_MAX_TOKENS))
    if len(source_content) > max_chars:
        source_content = source_content[:max_chars] + "\n\n[... content truncated ...]"
        _emit(on_event, "warn", "truncate",
              f"Source truncated to {max_chars:,} chars (config: digest.max_source_chars)")

    try:
        cfg = _load_agents_cfg(repo_root)
        model = cfg["digest_agent"]["model"]
    except Exception as exc:
        _emit(on_event, "error", "config",
              f"Failed to load agents.yaml: {exc}",
              traceback=traceback.format_exc())
        return _finalize_failed(f"Failed to load agents.yaml: {exc}")
    _emit(on_event, "info", "config",
          f"Using model={model}, max_tokens={max_tokens}")

    effective_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not effective_key:
        err = "ANTHROPIC_API_KEY is not set — digest cannot call Claude."
        _emit(on_event, "error", "api-key", err)
        return _finalize_failed(err)

    try:
        client = anthropic.Anthropic(api_key=effective_key)
        prompt = build_digest_prompt(source_content, raw_id, domain, repo_root)
        _emit(on_event, "info", "prompt",
              f"Built digest prompt ({len(prompt):,} chars)")
        _emit(on_event, "info", "call-claude",
              f"Calling Claude ({model})… this can take 10–30s")
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        page_text = extract_page_from_response(message.content[0].text.strip())
        usage = getattr(message, "usage", None)
        tok_info = ""
        if usage is not None:
            tok_info = (
                f" (input={getattr(usage, 'input_tokens', '?')}, "
                f"output={getattr(usage, 'output_tokens', '?')} tokens)"
            )
        _emit(on_event, "info", "response",
              f"Received response: {len(page_text):,} chars{tok_info}")
    except Exception as exc:
        err = f"Claude API error: {exc}"
        _emit(on_event, "error", "call-claude", err,
              traceback=traceback.format_exc())
        return _finalize_failed(err)

    _emit(on_event, "info", "validate", "Validating frontmatter…")
    result = _validate_page_text(page_text)
    if not result.valid:
        err = "; ".join(result.errors)
        _emit(on_event, "error", "validate",
              f"Frontmatter invalid: {err}",
              preview=page_text[:500])
        return _finalize_failed(err)
    _emit(on_event, "info", "validate-ok", "Frontmatter validated")

    fm, _ = parse_frontmatter_str(page_text)
    target_path = fm.get("target_path", "")
    if target_path and not check_path_traversal(target_path, domain):
        err = f"Invalid target_path: {target_path!r}"
        _emit(on_event, "error", "target-path", err)
        return _finalize_failed(err)
    _emit(on_event, "info", "target-path", f"Target: {target_path}")

    # Non-fatal: report near-duplicates so the reviewer knows what might be impacted.
    title = fm.get("title", "")
    if title:
        dupes = find_near_duplicates(title, domain, repo_root)
        if dupes:
            _emit(on_event, "warn", "duplicates",
                  f"Found {len(dupes)} near-duplicate page(s); consider merging",
                  duplicates=dupes)

    cand_filename = write_candidate(page_text, domain, repo_root)
    _emit(on_event, "info", "write",
          f"Wrote candidate → candidates/{domain}/pending/{cand_filename}",
          candidate=cand_filename)

    append_domain_log(repo_root, domain, "digest", f"{raw_id} → {cand_filename}")
    _emit(on_event, "done", "complete",
          f"Digest complete — candidate ready for review",
          candidate=cand_filename, domain=domain)

    final = _base_job()
    final["status"] = "completed"
    final["outputs"] = [cand_filename]
    _finalize_running(repo_root, job_id, "completed", final)
    return [cand_filename]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_agents_cfg(repo_root: Path) -> dict:
    agents_cfg_path = repo_root / "config" / "agents.yaml"
    if agents_cfg_path.exists():
        return load_agents_config(agents_cfg_path)
    return load_agents_config()


def _validate_page_text(page_text: str):
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8",
    ) as tf:
        tf.write(page_text)
        tf_path = tf.name
    try:
        return validate_frontmatter(Path(tf_path))
    finally:
        os.unlink(tf_path)


def _build_job_id(raw_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"job_{ts}_digest_{hash8(raw_id)}"


def _running_paths(repo_root: Path, job_id: str) -> tuple[Path, Path]:
    d = repo_root / "jobs" / "running"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{job_id}.yaml", d / f"{job_id}.events.jsonl"


def _write_running_record(
    repo_root: Path,
    job_id: str,
    domain: str,
    raw_id: str,
    created_at: str,
    started_at: str,
) -> None:
    """Write the initial running-state job YAML so observers can attach."""
    job = {
        "job_id": job_id,
        "job_type": "digest",
        "domain": domain,
        "status": "running",
        "created_at": created_at,
        "started_at": started_at,
        "heartbeat_at": now_iso(),
        "input": raw_id,
        "outputs": [],
        "agent": "digest-agent",
    }
    yaml_path, _ = _running_paths(repo_root, job_id)
    atomic_write(yaml_path, yaml.dump(job, allow_unicode=True, sort_keys=False))


def _append_event(repo_root: Path, job_id: str, evt: dict) -> None:
    """Append one event to the running events file so live viewers can tail it."""
    _, events_path = _running_paths(repo_root, job_id)
    try:
        with events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    except Exception:
        # Never let logging break the digest outcome.
        pass


def _finalize_running(
    repo_root: Path,
    job_id: str,
    bucket: str,
    final_job: dict,
) -> None:
    """Move running YAML → bucket with final fields; carry events file along."""
    dst_dir = repo_root / "jobs" / bucket
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_yaml = dst_dir / f"{job_id}.yaml"
    atomic_write(dst_yaml, yaml.dump(final_job, allow_unicode=True, sort_keys=False))

    running_yaml, running_events = _running_paths(repo_root, job_id)
    if running_yaml.exists():
        try:
            running_yaml.unlink()
        except OSError:
            pass
    if running_events.exists():
        dst_events = dst_dir / f"{job_id}.events.jsonl"
        try:
            if dst_events.exists():
                dst_events.unlink()
            running_events.rename(dst_events)
        except OSError:
            pass


