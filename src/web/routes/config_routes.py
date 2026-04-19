"""Edit config/app.yaml from the web UI."""
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.config import (
    DEFAULT_APP_CONFIG,
    app_config_path,
    dump_app_config,
    load_app_config,
)
from src.domains import DomainError, create_domain, delete_domain, rename_domain
from src.utils import atomic_write
from src.web.routes.shared import get_models_settings, list_domains

router = APIRouter()


def _lines_to_list(text: str) -> list[str]:
    """Split a textarea value into a list, stripping blanks and comments."""
    out: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def _as_int(val, fallback: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return fallback


def _as_float(val, fallback: float) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return fallback


def _render(
    request: Request,
    *,
    cfg: dict,
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    templates = request.app.state.templates
    repo_root: Path = request.app.state.repo_root
    models = get_models_settings(repo_root)
    return templates.TemplateResponse(request, "config.html", {
        "cfg": cfg,
        "domains": list_domains(repo_root),
        "config_path": str(app_config_path(repo_root)),
        "available_themes": (cfg.get("ui") or {}).get("themes")
            or DEFAULT_APP_CONFIG["ui"]["themes"],
        "available_models": models["available"],
        "main_model": models["main"],
        "secondary_model": models["secondary"],
        "message": message,
        "error": error,
    })


@router.get("/config", response_class=HTMLResponse)
async def config_view(
    request: Request,
    message: str = "",
    error: str = "",
):
    repo_root: Path = request.app.state.repo_root
    return _render(
        request,
        cfg=load_app_config(repo_root=repo_root),
        message=message, error=error,
    )


@router.post("/config/domain/create")
async def config_domain_create(request: Request, new_domain: str = Form(...)):
    repo_root: Path = request.app.state.repo_root
    try:
        name = create_domain(new_domain, repo_root)
    except DomainError as exc:
        return RedirectResponse(
            f"/config?error={_q(str(exc))}", status_code=303,
        )
    return RedirectResponse(
        f"/config?message={_q(f'Domain {name!r} created. Start ingesting.')}",
        status_code=303,
    )


@router.post("/config/domain/rename")
async def config_domain_rename(
    request: Request,
    old_domain: str = Form(...),
    new_domain: str = Form(...),
):
    repo_root: Path = request.app.state.repo_root
    try:
        summary = rename_domain(old_domain, new_domain, repo_root)
    except DomainError as exc:
        return RedirectResponse(
            f"/config?error={_q(str(exc))}", status_code=303,
        )
    bits = [
        f"Renamed {summary.old!r} → {summary.new!r}",
        f"{summary.pages_updated} page(s)",
        f"{summary.candidates_updated} candidate(s)",
    ]
    if summary.agents_updated:
        bits.append(f"agents: {', '.join(summary.agents_updated)}")
    if summary.app_default_updated:
        bits.append("default_domain updated")
    resp = RedirectResponse(f"/config?message={_q('. '.join(bits))}", status_code=303)
    # Users currently scoped to the old cookie value would otherwise get
    # bounced back to the default — clear it so they re-pick from the new list.
    resp.delete_cookie("2brain-domain", path="/")
    return resp


@router.post("/config/domain/delete")
async def config_domain_delete(
    request: Request,
    domain: str = Form(...),
    confirm_1: str = Form(...),
    confirm_2: str = Form(...),
):
    repo_root: Path = request.app.state.repo_root
    try:
        summary = delete_domain(domain, confirm_1, confirm_2, repo_root)
    except DomainError as exc:
        return RedirectResponse(
            f"/config?error={_q(str(exc))}", status_code=303,
        )
    bits = [f"Deleted domain {summary.domain!r}"]
    if summary.candidates_dir_removed:
        bits.append("candidates tree removed")
    if summary.agents_cleared:
        bits.append(f"cleared agent configs: {', '.join(summary.agents_cleared)}")
    if summary.app_default_fell_back_to:
        bits.append(f"default_domain → {summary.app_default_fell_back_to!r}")
    resp = RedirectResponse(
        f"/config?message={_q('. '.join(bits))}", status_code=303,
    )
    resp.delete_cookie("2brain-domain", path="/")
    return resp


def _q(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="")


@router.post("/config", response_class=HTMLResponse)
async def config_save(
    request: Request,
    default_domain: str = Form(...),
    web_ui_host: str = Form("127.0.0.1"),
    web_ui_port: int = Form(5000),
    web_ui_auto_open_browser: str = Form(""),
    audit_enabled: str = Form(""),
    audit_log_queries: str = Form(""),
    source_types: str = Form(""),
    suggested_tags: str = Form(""),
    digest_max_source_chars: str = Form(""),
    digest_max_tokens: str = Form(""),
    lint_stale_days: str = Form(""),
    lint_stuck_job_minutes: str = Form(""),
    lint_low_confidence_threshold: str = Form(""),
    ui_default_theme: str = Form("light"),
    ui_themes: str = Form(""),
    models_available: str = Form(""),
    models_main: str = Form(""),
    models_secondary: str = Form(""),
):
    repo_root: Path = request.app.state.repo_root
    existing = load_app_config(repo_root=repo_root)

    defaults = DEFAULT_APP_CONFIG

    new_cfg = dict(existing)
    new_cfg.setdefault("version", "1")
    new_cfg.setdefault("repo_root", ".")

    new_cfg["default_domain"] = (
        default_domain.strip() or existing.get("default_domain", "edge-ai")
    )
    new_cfg["web_ui"] = {
        "host": web_ui_host.strip() or "127.0.0.1",
        "port": int(web_ui_port),
        "auto_open_browser": bool(web_ui_auto_open_browser),
    }
    new_cfg["audit"] = {
        "enabled": bool(audit_enabled),
        "log_queries": bool(audit_log_queries),
    }

    new_source_types = _lines_to_list(source_types)
    new_cfg["source_types"] = new_source_types or defaults["source_types"]
    new_cfg["suggested_tags"] = _lines_to_list(suggested_tags)

    new_cfg["digest"] = {
        "max_source_chars": _as_int(digest_max_source_chars, defaults["digest"]["max_source_chars"]),
        "max_tokens": _as_int(digest_max_tokens, defaults["digest"]["max_tokens"]),
    }
    new_cfg["lint"] = {
        "stale_days": _as_int(lint_stale_days, defaults["lint"]["stale_days"]),
        "stuck_job_minutes": _as_int(lint_stuck_job_minutes, defaults["lint"]["stuck_job_minutes"]),
        "low_confidence_threshold": _as_float(
            lint_low_confidence_threshold, defaults["lint"]["low_confidence_threshold"],
        ),
    }

    parsed_themes = _lines_to_list(ui_themes) or defaults["ui"]["themes"]
    chosen_theme = ui_default_theme.strip() or "light"
    if chosen_theme not in parsed_themes:
        parsed_themes = [chosen_theme] + parsed_themes
    new_cfg["ui"] = {
        "default_theme": chosen_theme,
        "themes": parsed_themes,
    }

    avail = _lines_to_list(models_available) or defaults["models"]["available"]
    main = (models_main.strip() or defaults["models"]["main"])
    secondary = (models_secondary.strip() or defaults["models"]["secondary"])
    # Any custom main/secondary the user typed gets promoted into the
    # available list so it shows up in later <select> dropdowns.
    for m in (main, secondary):
        if m and m not in avail:
            avail.insert(0, m)
    new_cfg["models"] = {
        "available": avail,
        "main": main,
        "secondary": secondary,
    }

    try:
        atomic_write(app_config_path(repo_root), dump_app_config(new_cfg))
        return _render(request, cfg=new_cfg, message="Configuration saved.")
    except Exception as exc:
        return _render(request, cfg=existing, error=f"Failed to save: {exc}")
