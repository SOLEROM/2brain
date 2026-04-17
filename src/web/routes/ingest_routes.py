import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from src.ingest import ingest_source

router = APIRouter()

SOURCE_TYPES = ["url", "text", "note", "pdf", "repo", "image", "video", "api"]


def _list_domains(repo_root: Path) -> list[str]:
    domains_dir = repo_root / "domains"
    if not domains_dir.exists():
        return ["edge-ai"]
    return sorted(
        d.name for d in domains_dir.iterdir()
        if d.is_dir() and (d / "domain.yaml").exists()
    ) or ["edge-ai"]


async def _fetch_url(url: str) -> tuple[str, str]:
    import httpx
    from html.parser import HTMLParser

    class _TitleExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self._in_title = False
            self.title = ""

        def handle_starttag(self, tag, attrs):
            if tag == "title":
                self._in_title = True

        def handle_endtag(self, tag):
            if tag == "title":
                self._in_title = False

        def handle_data(self, data):
            if self._in_title:
                self.title += data

    def _do_fetch():
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        return resp.text

    content = await asyncio.to_thread(_do_fetch)
    extractor = _TitleExtractor()
    extractor.feed(content)
    title = extractor.title.strip() or url
    return content, title


@router.get("/ingest", response_class=HTMLResponse)
async def ingest_form(request: Request):
    templates = request.app.state.templates
    repo_root: Path = request.app.state.repo_root
    domains = _list_domains(repo_root)
    return templates.TemplateResponse(request, "ingest.html", {
        "domain": domains[0],
        "domains": domains,
        "source_types": SOURCE_TYPES,
        "result": None,
        "error": None,
    })


@router.post("/ingest", response_class=HTMLResponse)
async def ingest_submit(
    request: Request,
    url: str = Form(default=""),
    content: str = Form(default=""),
    title: str = Form(default=""),
    source_type: str = Form(default="text"),
    domain_hint: str = Form(default=""),
):
    templates = request.app.state.templates
    repo_root: Path = request.app.state.repo_root
    domains = _list_domains(repo_root)

    actual_content = content.strip()
    actual_title = title.strip()
    actual_url = url.strip()
    error = None

    try:
        if actual_url:
            source_type = "url"
            fetched_content, fetched_title = await _fetch_url(actual_url)
            actual_content = fetched_content
            if not actual_title:
                actual_title = fetched_title
        elif not actual_content:
            raise ValueError("Provide either a URL or paste content.")

        if not actual_title:
            actual_title = "Untitled source"

        def _do_ingest():
            return ingest_source(
                content=actual_content,
                title=actual_title,
                source_type=source_type,
                url=actual_url or None,
                domain_hint=domain_hint or None,
                submitted_by="user",
                repo_root=repo_root,
            )

        raw_id = await asyncio.to_thread(_do_ingest)
        result = {"raw_id": raw_id, "title": actual_title, "domain_hint": domain_hint}
    except Exception as exc:
        error = str(exc)
        result = None

    return templates.TemplateResponse(request, "ingest.html", {
        "domain": domain_hint or domains[0],
        "domains": domains,
        "source_types": SOURCE_TYPES,
        "result": result,
        "error": error,
        "form": {
            "url": actual_url,
            "title": actual_title,
            "source_type": source_type,
            "domain_hint": domain_hint,
        },
    })
