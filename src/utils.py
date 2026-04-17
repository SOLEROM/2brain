import hashlib
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def coerce_datetimes(obj: Any) -> Any:
    """Recursively replace datetime/date values with ISO-8601 strings.

    YAML auto-parses unquoted ISO timestamps (e.g. ``created_at: 2026-04-17T...``)
    into ``datetime`` objects. Templates and downstream consumers expect
    strings (so ``value[:10]`` works for the date prefix), so every read of a
    frontmatter dict is normalised here.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: coerce_datetimes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [coerce_datetimes(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(coerce_datetimes(x) for x in obj)
    return obj


def slug_from_title(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    if len(s) > 60:
        s = s[:60].rsplit("-", 1)[0]
    return s


def hash8(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:8]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def today_iso() -> str:
    return date.today().isoformat()


def atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically: write to a unique temp file then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def append_line(path: Path, line: str) -> None:
    """Append a single line to a file, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not line.endswith("\n"):
        line += "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def append_domain_log(repo_root: Path, domain: str, operation: str, detail: str) -> None:
    """Append a standard entry to domains/<domain>/log.md. No-op if log missing."""
    log_path = repo_root / "domains" / domain / "log.md"
    if not log_path.exists():
        return
    append_line(log_path, f"\n## [{today_iso()}] {operation} | {detail}")
