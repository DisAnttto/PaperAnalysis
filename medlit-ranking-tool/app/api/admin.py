"""Internal admin endpoints — mode switching and runtime controls.

These are not part of the public API and have no auth (internal-only tool).
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import llm_is_configured, settings

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class SetModeRequest(BaseModel):
    mode: Literal["demo", "dev", "prod"]


class SetModeResponse(BaseModel):
    previous_mode: str
    current_mode: str
    pubmed_live: bool
    llm_configured: bool


@router.post("/set-mode", response_model=SetModeResponse)
async def set_mode(body: SetModeRequest) -> SetModeResponse:
    """Switch APP_MODE at runtime (in-memory only; does not persist to .env).

    Allows toggling between demo (seeded fixtures) and live pipeline
    without restarting the server.
    """
    previous = settings.APP_MODE
    settings.APP_MODE = body.mode
    return SetModeResponse(
        previous_mode=previous,
        current_mode=settings.APP_MODE,
        pubmed_live=settings.APP_MODE != "demo",
        llm_configured=llm_is_configured(),
    )
