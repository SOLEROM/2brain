import asyncio
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from src.ingest import ingest_source
from src.web.routes.shared import get_source_types, get_suggested_tags, list_domains

router = APIRouter()


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
):
    repo_root: Path = request.app.state.repo_root
    actual_url = url.strip()
    actual_title = title.strip()
    actual_content = content.strip()
    active = getattr(request.state, "current_domain", None) or list_domains(repo_root)[0]
    domain = domain_hint or active

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    form_state = {
        "url": actual_url, "content": actual_content, "title": actual_title,
        "source_type": source_type, "domain_hint": domain_hint, "tags": tags,
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
        return _render(
            request,
            domain=domain,
            result={"raw_id": raw_id, "title": actual_title, "domain_hint": domain_hint},
        )
    except Exception as exc:
        return _render(request, domain=domain, form=form_state, error=str(exc))
