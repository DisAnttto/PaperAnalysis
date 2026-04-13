"""Health and system status endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_llm_client_config, settings

router = APIRouter(tags=["meta"])


class HealthResponse(BaseModel):
    status: str
    app_env: str
    app_mode: str
    llm_backend: str
    llm_model: str
    llm_base_url: str
    llm_configured: bool
    pubmed_live: bool


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return system status information."""
    is_demo = settings.APP_MODE == "demo"
    cfg = get_llm_client_config()
    base_url = cfg.base_url or ""
    return HealthResponse(
        status="ok",
        app_env=settings.APP_ENV,
        app_mode=settings.APP_MODE,
        llm_backend=cfg.backend,
        llm_model=cfg.model,
        llm_base_url=base_url,
        llm_configured=bool(cfg.api_key),
        pubmed_live=not is_demo,
    )
