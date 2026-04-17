from pathlib import Path
from typing import Optional
import yaml
from src.models import PageFrontmatter, ValidationResult
from src.utils import coerce_datetimes


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Returns (frontmatter_dict, body_text). Empty dict if no frontmatter.

    datetime/date values parsed by YAML are coerced to ISO-8601 strings so
    templates can safely slice them (e.g. ``created_at[:10]``).
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        fm = {}
    body = parts[2].lstrip("\n")
    return coerce_datetimes(fm), body


def validate_frontmatter(path: Path) -> ValidationResult:
    """Validate a candidate page's frontmatter. Returns ValidationResult."""
    fm, _ = parse_frontmatter(path)
    if not fm:
        return ValidationResult(valid=False, errors=["No YAML frontmatter found"])

    errors: list[str] = []
    required = ["title", "domain", "type", "status", "confidence",
                "sources", "created_at", "updated_at", "tags"]
    for field in required:
        if field not in fm:
            errors.append(f"Missing required field: '{field}'")

    if errors:
        return ValidationResult(valid=False, errors=errors)

    try:
        PageFrontmatter(**fm)
    except Exception as e:
        for err in str(e).split("\n"):
            if err.strip():
                errors.append(err.strip())
        return ValidationResult(valid=False, errors=errors)

    return ValidationResult(valid=True)


def check_path_traversal(target_path: str, domain: str) -> bool:
    """Return True if target_path is safely within domains/<domain>/."""
    if not target_path or target_path.startswith("/"):
        return False
    p = Path(target_path)
    parts = p.parts
    if len(parts) < 2:
        return False
    if parts[0] != "domains" or parts[1] != domain:
        return False
    # Resolve to check for .. traversal
    try:
        resolved = Path("/" + target_path).resolve()
        base = Path(f"/domains/{domain}").resolve()
        return str(resolved).startswith(str(base))
    except Exception:
        return False
