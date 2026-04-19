import asyncio
import hashlib
import html as html_lib
import re
import urllib.parse
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from src.ingest import ingest_source
from src.web.routes.shared import get_source_types, get_suggested_tags, list_domains, load_yaml

router = APIRouter()


# -----------------------------------------------------------------------------
# Raw sources list (merged from the old /sources tab — now shown on /ingest)
# -----------------------------------------------------------------------------

def _load_raw_sources(repo_root: Path) -> list[dict]:
    """Return one dict per raw source under inbox/raw/, newest first."""
    raw_dir = repo_root / "inbox" / "raw"
    if not raw_dir.exists():
        return []
    items: list[dict] = []
    for entry in sorted(raw_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        meta = load_yaml(entry / "metadata.yaml")
        if not meta:
            continue
        items.append({
            "raw_id": entry.name,
            "title": meta.get("title", entry.name),
            "source_type": meta.get("source_type", ""),
            "ingested_at": meta.get("ingested_at", ""),
            "domain_hint": meta.get("domain_hint", ""),
            "url": meta.get("url", ""),
            "fetch_status": meta.get("fetch_status", "ok"),
        })
    return items


# -----------------------------------------------------------------------------
# Media download (best-effort)
# -----------------------------------------------------------------------------

_MEDIA_EXTS = ("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp",
               "mp4", "webm", "mov", "m4v", "pdf")
_MEDIA_ATTR_RE = re.compile(
    r'(?:src|href|poster)\s*=\s*["\']([^"\']+?\.(?:' + "|".join(_MEDIA_EXTS) + r'))(?:\?[^"\']*)?["\']',
    re.IGNORECASE,
)
_MD_IMAGE_RE = re.compile(r'!\[[^\]]*\]\(\s*([^)\s]+)', re.IGNORECASE)
_MAX_MEDIA_COUNT = 30
_MAX_MEDIA_BYTES = 8 * 1024 * 1024  # 8 MB per asset


def _extract_media_urls(content: str, base_url: str) -> list[str]:
    """Return absolute URLs of media assets referenced by the content."""
    found: list[str] = []
    seen: set[str] = set()

    def _add(raw_url: str) -> None:
        if not raw_url or raw_url.startswith("data:"):
            return
        unescaped = html_lib.unescape(raw_url).strip()
        if not unescaped:
            return
        abs_url = urllib.parse.urljoin(base_url or "", unescaped)
        if not abs_url.startswith(("http://", "https://")):
            return
        if abs_url in seen:
            return
        seen.add(abs_url)
        found.append(abs_url)

    for m in _MEDIA_ATTR_RE.finditer(content or ""):
        _add(m.group(1))
        if len(found) >= _MAX_MEDIA_COUNT:
            return found
    for m in _MD_IMAGE_RE.finditer(content or ""):
        _add(m.group(1))
        if len(found) >= _MAX_MEDIA_COUNT:
            return found
    return found


def _safe_asset_filename(url: str) -> str:
    """Derive a collision-resistant on-disk name for a downloaded asset."""
    parsed = urllib.parse.urlparse(url)
    raw_name = Path(parsed.path).name or "asset"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("-") or "asset"
    if len(safe) > 80:
        stem, dot, ext = safe.rpartition(".")
        safe = (stem[:60] + (dot + ext if dot else ""))
    digest = hashlib.sha256(url.encode()).hexdigest()[:8]
    if "." in safe:
        stem, ext = safe.rsplit(".", 1)
        return f"{stem}-{digest}.{ext}"
    return f"{safe}-{digest}"


def _download_one_media(url: str, dest: Path) -> Optional[int]:
    """Download a single asset with strict size/time limits. Returns bytes written or None."""
    import httpx

    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=10) as r:
            if r.status_code != 200:
                return None
            total = 0
            chunks: list[bytes] = []
            for chunk in r.iter_bytes():
                total += len(chunk)
                if total > _MAX_MEDIA_BYTES:
                    return None
                chunks.append(chunk)
        dest.write_bytes(b"".join(chunks))
        return total
    except Exception:
        return None


async def _download_media_assets(content: str, base_url: str, assets_dir: Path) -> list[dict]:
    """Best-effort fetch of media referenced by the ingested content.

    Failures per asset are silently skipped so the ingest succeeds even when
    some assets 404 or time out.
    """
    urls = _extract_media_urls(content, base_url)
    if not urls:
        return []
    assets_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    for url in urls:
        name = _safe_asset_filename(url)
        dest = assets_dir / name
        size = await asyncio.to_thread(_download_one_media, url, dest)
        if size is not None:
            saved.append({"url": url, "file": name, "bytes": size})
    return saved


def _record_media_in_metadata(raw_dir: Path, assets: list[dict], attempted: bool) -> None:
    """Merge media-download results into the raw source's metadata.yaml."""
    meta_path = raw_dir / "metadata.yaml"
    if not meta_path.exists():
        return
    try:
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return
    meta["download_media"] = attempted
    meta["media_assets"] = assets
    meta_path.write_text(yaml.dump(meta, allow_unicode=True), encoding="utf-8")


# -----------------------------------------------------------------------------
# GitHub URL handling
# -----------------------------------------------------------------------------

# Repo root: https://github.com/<owner>/<repo>[.git][/][?...]
GITHUB_REPO_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?(?:\?.*)?$",
    re.IGNORECASE,
)
# Specific file: https://github.com/<owner>/<repo>/blob/<branch>/<path>
GITHUB_BLOB_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/blob/(?P<branch>[^/]+)/(?P<path>.+)$",
    re.IGNORECASE,
)


def parse_github_url(url: str) -> Optional[tuple[str, dict]]:
    """Classify a URL as a GitHub repo root or blob, or return None.

    Returns ('repo', {'owner', 'repo'}) or ('blob', {'owner','repo','branch','path'}).
    """
    u = (url or "").strip()
    if not u:
        return None
    m = GITHUB_BLOB_RE.match(u)
    if m:
        return ("blob", m.groupdict())
    m = GITHUB_REPO_RE.match(u)
    if m:
        return ("repo", m.groupdict())
    return None


async def _fetch_github_readme(owner: str, repo: str) -> tuple[str, str]:
    """Fetch the default-branch README via the GitHub API (raw accept header),
    with raw.githubusercontent.com fallbacks for rate-limit / API hiccups.
    """
    import httpx

    def _api_fetch() -> httpx.Response:
        return httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}/readme",
            headers={
                "Accept": "application/vnd.github.raw",
                "User-Agent": "2brain",
            },
            follow_redirects=True,
            timeout=30,
        )

    resp = await asyncio.to_thread(_api_fetch)
    if resp.status_code == 200 and (resp.text or "").strip():
        return resp.text, f"{owner}/{repo} — README"

    last_status = resp.status_code
    # Fallback: try common README filenames on common default-branch names.
    for branch in ("HEAD", "main", "master"):
        for fname in ("README.md", "readme.md", "Readme.md", "README", "README.rst"):
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{fname}"

            def _raw_fetch(u: str = raw_url) -> httpx.Response:
                return httpx.get(u, follow_redirects=True, timeout=30)

            rr = await asyncio.to_thread(_raw_fetch)
            if rr.status_code == 200 and (rr.text or "").strip():
                return rr.text, f"{owner}/{repo} — README"
            last_status = rr.status_code

    raise ValueError(
        f"Could not fetch README for github.com/{owner}/{repo} "
        f"(last HTTP status: {last_status})"
    )


async def _fetch_github_blob(owner: str, repo: str, branch: str, path: str) -> tuple[str, str]:
    import httpx
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"

    def _fetch() -> httpx.Response:
        return httpx.get(raw_url, follow_redirects=True, timeout=30)

    resp = await asyncio.to_thread(_fetch)
    if resp.status_code != 200:
        raise ValueError(f"Could not fetch {raw_url} (HTTP {resp.status_code})")
    return resp.text, f"{owner}/{repo}:{path} @ {branch}"


async def _fetch_github_tree(owner: str, repo: str) -> Optional[list[dict]]:
    """Fetch the top-level directory listing for a repo. None on failure."""
    import httpx

    def _fetch() -> httpx.Response:
        return httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "2brain",
            },
            follow_redirects=True,
            timeout=30,
        )

    resp = await asyncio.to_thread(_fetch)
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, list) else None


def _format_tree_md(entries: list[dict]) -> str:
    """Render a top-level repo listing as a markdown bullet list (dirs first)."""
    lines: list[str] = []
    for e in sorted(
        entries,
        key=lambda x: (x.get("type") != "dir", str(x.get("name", "")).lower()),
    ):
        name = str(e.get("name", "?"))
        typ = str(e.get("type", ""))
        size = e.get("size")
        icon = "📁" if typ == "dir" else "📄"
        if typ == "dir":
            lines.append(f"- {icon} `{name}/`")
        elif isinstance(size, int):
            lines.append(f"- {icon} `{name}`  _({size:,} bytes)_")
        else:
            lines.append(f"- {icon} `{name}`")
    return "\n".join(lines)


async def _fetch_github_repo_material(owner: str, repo: str) -> tuple[str, str]:
    """Compose the raw source for a GitHub repo: README + top-level tree."""
    readme_text, title = await _fetch_github_readme(owner, repo)
    tree_entries = await _fetch_github_tree(owner, repo)

    parts: list[str] = [
        f"# {owner}/{repo}",
        "",
        f"Repository: https://github.com/{owner}/{repo}",
        "",
        "---",
        "",
        "## README",
        "",
        readme_text.strip(),
    ]
    if tree_entries:
        parts.extend([
            "",
            "---",
            "",
            f"## Repository Tree (top level — {len(tree_entries)} entries)",
            "",
            _format_tree_md(tree_entries),
        ])
    return "\n".join(parts), title


async def _fetch_url(url: str) -> tuple[str, str]:
    """Fetch a URL and try to extract a <title>. Runs blocking httpx in a thread.

    GitHub URLs are handled specially: repo roots resolve to README + top-level
    tree; blob URLs resolve to the raw file contents.
    """
    import httpx

    gh = parse_github_url(url)
    if gh is not None:
        kind, parts = gh
        if kind == "repo":
            return await _fetch_github_repo_material(parts["owner"], parts["repo"])
        if kind == "blob":
            return await _fetch_github_blob(
                parts["owner"], parts["repo"], parts["branch"], parts["path"],
            )

    def _do_fetch() -> str:
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        return resp.text

    content = await asyncio.to_thread(_do_fetch)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    title = (title_match.group(1).strip() if title_match else url) or url
    return content, title


def _render(request: Request, *, domain: str, form: Optional[dict] = None,
            result: Optional[dict] = None, error: Optional[str] = None) -> HTMLResponse:
    templates = request.app.state.templates
    repo_root: Path = request.app.state.repo_root
    return templates.TemplateResponse(request, "ingest.html", {
        "domain": domain,
        "domains": list_domains(repo_root),
        "source_types": get_source_types(repo_root),
        "suggested_tags": get_suggested_tags(repo_root),
        "form": form,
        "result": result,
        "error": error,
        "sources": _load_raw_sources(repo_root),
    })


@router.get("/ingest", response_class=HTMLResponse)
async def ingest_form(request: Request):
    repo_root: Path = request.app.state.repo_root
    active = getattr(request.state, "current_domain", None) or list_domains(repo_root)[0]
    return _render(request, domain=active)


@router.post("/ingest", response_class=HTMLResponse)
async def ingest_submit(
    request: Request,
    url: str = Form(default=""),
    content: str = Form(default=""),
    title: str = Form(default=""),
    source_type: str = Form(default="text"),
    domain_hint: str = Form(default=""),
    tags: str = Form(default=""),
    download_media: Optional[str] = Form(default=None),
):
    repo_root: Path = request.app.state.repo_root
    actual_url = url.strip()
    actual_title = title.strip()
    actual_content = content.strip()
    active = getattr(request.state, "current_domain", None) or list_domains(repo_root)[0]
    domain = domain_hint or active

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    want_media = (download_media or "").lower() in ("on", "1", "true", "yes")

    form_state = {
        "url": actual_url, "content": actual_content, "title": actual_title,
        "source_type": source_type, "domain_hint": domain_hint, "tags": tags,
        "download_media": want_media,
    }

    try:
        if actual_url:
            gh = parse_github_url(actual_url)
            if gh is not None:
                # GitHub repos are ingested as their README + top-level tree.
                source_type = "repo"
                owner = gh[1].get("owner", "").lower()
                for auto in ("github", owner):
                    if auto and auto not in tag_list:
                        tag_list.append(auto)
            else:
                source_type = "url"
            fetched, fetched_title = await _fetch_url(actual_url)
            actual_content = fetched
            actual_title = actual_title or fetched_title
        elif not actual_content:
            raise ValueError("Provide either a URL or paste content.")
        actual_title = actual_title or "Untitled source"

        raw_id = await asyncio.to_thread(
            ingest_source,
            content=actual_content,
            title=actual_title,
            source_type=source_type,
            url=actual_url or None,
            domain_hint=domain_hint or None,
            submitted_by="user",
            tags=tag_list,
            repo_root=repo_root,
        )

        media_assets: list[dict] = []
        if want_media and actual_url:
            raw_dir = repo_root / "inbox" / "raw" / raw_id
            media_assets = await _download_media_assets(
                actual_content, actual_url, raw_dir / "assets",
            )
            _record_media_in_metadata(raw_dir, media_assets, attempted=True)
        elif actual_url:
            # Still record that media was offered but declined, for provenance.
            _record_media_in_metadata(repo_root / "inbox" / "raw" / raw_id, [], attempted=False)

        return _render(
            request,
            domain=domain,
            result={
                "raw_id": raw_id,
                "title": actual_title,
                "domain_hint": domain_hint,
                "media_count": len(media_assets),
                "media_attempted": want_media and bool(actual_url),
            },
        )
    except Exception as exc:
        return _render(request, domain=domain, form=form_state, error=str(exc))
