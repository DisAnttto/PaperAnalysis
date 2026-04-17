"""Report generation API endpoints."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.models.report import SearchReport
from app.models.search import SearchRequest
from app.services import db
from app.services.report_generator import generate_report, report_to_markdown

router = APIRouter(prefix="/api/v1", tags=["report"])


def _report_from_run_id(run_id: str) -> SearchReport:
    """Load a persisted run log and build its SearchReport, or raise 404."""
    run_log = db.load_run_log(run_id)
    if run_log is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    request = SearchRequest(query=run_log.query, pool_size=100, max_results=20)
    return generate_report(
        request=request,
        ranked=[],
        stage_counts=run_log.stage_counts,
        run_id=run_id,
    )


@router.get("/report/{run_id}", response_model=SearchReport)
async def get_report(run_id: str) -> SearchReport:
    """Generate a structured report from a completed search run."""
    return _report_from_run_id(run_id)


@router.get("/report/{run_id}/markdown", response_class=PlainTextResponse)
async def get_report_markdown(run_id: str) -> str:
    """Generate a markdown report from a completed search run."""
    return report_to_markdown(_report_from_run_id(run_id))
