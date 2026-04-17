"""Interpret API — NL finding parser only."""

from fastapi import APIRouter

from app.models.interpret import FindingParseRequest, FindingParseResponse
from app.services.interpret import parse_finding_text

router = APIRouter(prefix="/api/v1", tags=["interpret"])


@router.post("/interpret/parse", response_model=FindingParseResponse)
async def interpret_parse(req: FindingParseRequest) -> FindingParseResponse:
    """Parse a natural-language clinical finding into structured search fields."""
    return await parse_finding_text(req.text)
