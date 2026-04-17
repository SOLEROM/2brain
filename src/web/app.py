from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from src.web.routes import candidates, wiki, query_routes


def create_app(repo_root: Path = Path(".")) -> FastAPI:
    app = FastAPI(title="2brain Review UI")

    templates_dir = Path(__file__).parent / "templates"
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)

    templates = Jinja2Templates(directory=str(templates_dir))
    app.state.repo_root = repo_root
    app.state.templates = templates

    app.include_router(candidates.router)
    app.include_router(wiki.router)
    app.include_router(query_routes.router)

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


def get_app() -> FastAPI:
    return create_app(Path("."))
