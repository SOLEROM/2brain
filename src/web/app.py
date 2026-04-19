import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.agents.scheduler import scheduler_loop
from src.config import load_app_config
from src.web.routes import (
    about,
    agents as agents_routes,
    ask,
    candidates,
    config_routes,
    digest_routes,
    health,
    ingest_routes,
    jobs,
    query_routes,
    wiki,
)
from src.web.routes.shared import current_domain, default_domain, list_domains

log = logging.getLogger(__name__)


def create_app(repo_root: Path = Path(".")) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        # Background agent scheduler. Disable by setting TWOBRAIN_DISABLE_SCHEDULER=1
        # (tests; multi-worker deployments that would otherwise double-fire).
        if os.environ.get("TWOBRAIN_DISABLE_SCHEDULER"):
            log.info("agent scheduler disabled via TWOBRAIN_DISABLE_SCHEDULER")
            app.state.scheduler_task = None
            app.state.scheduler_stop = None
            yield
            return
        tick = int(os.environ.get("TWOBRAIN_SCHEDULER_TICK", "60"))
        app.state.scheduler_stop = asyncio.Event()
        app.state.scheduler_task = asyncio.create_task(
            scheduler_loop(repo_root, tick_seconds=tick, stop_event=app.state.scheduler_stop)
        )
        log.info("agent scheduler started (tick=%ds)", tick)
        try:
            yield
        finally:
            app.state.scheduler_stop.set()
            app.state.scheduler_task.cancel()
            try:
                await app.state.scheduler_task
            except (asyncio.CancelledError, Exception):
                pass

    app = FastAPI(title="2brain Review UI", lifespan=_lifespan)

    templates_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)

    templates = Jinja2Templates(directory=str(templates_dir))

    def _ui_defaults():
        cfg = load_app_config(repo_root=repo_root)
        ui = cfg.get("ui") or {}
        return {
            "ui_default_theme": ui.get("default_theme", "light"),
            "ui_themes": ui.get("themes", ["light", "dark", "hackers-green"]),
        }

    templates.env.globals["ui_defaults"] = _ui_defaults

    app.state.repo_root = repo_root
    app.state.templates = templates

    @app.middleware("http")
    async def inject_session_domain(request: Request, call_next):
        try:
            request.state.all_domains = list_domains(repo_root)
            request.state.current_domain = current_domain(request, repo_root)
        except Exception:
            request.state.all_domains = ["edge-ai"]
            request.state.current_domain = "edge-ai"
        return await call_next(request)

    @app.get("/")
    async def root(request: Request):
        return RedirectResponse(f"/wiki/{request.state.current_domain}")

    app.include_router(wiki.router)
    app.include_router(ingest_routes.router)
    app.include_router(digest_routes.router)
    app.include_router(candidates.router)
    app.include_router(query_routes.router)
    app.include_router(ask.router)
    app.include_router(agents_routes.router)
    app.include_router(jobs.router)
    app.include_router(health.router)
    app.include_router(config_routes.router)
    app.include_router(about.router)

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


def get_app() -> FastAPI:
    return create_app(Path("."))
