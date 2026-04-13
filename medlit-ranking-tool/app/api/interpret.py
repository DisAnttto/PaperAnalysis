"""Outcome interpretation API."""

from fastapi import APIRouter

from app.models.interpret import InterpretRequest, InterpretResponse
from app.services.interpret import interpret_finding

router = APIRouter(prefix="/api/v1", tags=["interpret"])


@router.post("/interpret", response_model=InterpretResponse)
async def interpret_endpoint(req: InterpretRequest) -> InterpretResponse:
    return await interpret_finding(req)
