import hashlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import admin, health, interpret, papers, qa, report, retrieval, search
from app.core.config import get_llm_client_config, settings
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(
    title="MedLit Ranking Tool",
    description="Automated ingestion, extraction, and ranking of medical literature.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Prevent browsers from caching QA console static assets (dev-friendly)."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


app.add_middleware(NoCacheStaticMiddleware)

# --- Static files and templates ---
_BASE = Path(__file__).parent


def _static_version() -> str:
    """Short fingerprint from mtimes so cache-bust URLs change when JS/CSS change."""
    static_dir = _BASE / "static"
    mtimes: list[str] = []
    for name in ("app.js", "style.css"):
        try:
            mtimes.append(str((static_dir / name).stat().st_mtime_ns))
        except OSError:
            pass
    return hashlib.md5(",".join(mtimes).encode(), usedforsecurity=False).hexdigest()[:8]


app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")
_templates = Jinja2Templates(directory=_BASE / "templates")

# --- API routers ---
app.include_router(health.router)
app.include_router(search.router)
app.include_router(papers.router)
app.include_router(admin.router)
app.include_router(qa.router)
app.include_router(retrieval.router)
app.include_router(interpret.router)
app.include_router(report.router)


# --- QA Console frontend ---
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def qa_console(request: Request) -> HTMLResponse:
    return _templates.TemplateResponse(
        request,
        "index.html",
        {
            "app_mode": settings.APP_MODE,
            "llm_model": get_llm_client_config().model,
            "static_v": _static_version(),
        },
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )
