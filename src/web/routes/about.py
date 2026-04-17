from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "about.html", {})
