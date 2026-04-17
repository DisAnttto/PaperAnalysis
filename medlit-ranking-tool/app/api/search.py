"""POST /api/v1/search and /api/v1/search/stream endpoints."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from loguru import logger

from app.api.models import SearchResponse
from app.core.config import settings
from app.models.paper import Paper
from app.models.run_log import RetrievalRunLog, StageCounts
from app.models.search import SearchRequest
from app.normalization import normalize_extraction
from app.ranking.composite import rank_papers, score_composite
from app.ranking.product_display import format_product_table_label
from app.ranking.relevance_agent import llm_relevance_raw, merge_relevance_llm
from app.services.intent_router import get_routing
from app.services.post_filters import apply_post_filters

router = APIRouter(prefix="/api/v1", tags=["search"])


def _papers_in_uid_order(papers: list[Paper], uids: list[str]) -> list[Paper]:
    """Reorder papers to match ``uids`` (drops unknown ids)."""
    by_uid = {p.uid: p for p in papers}
    return [by_uid[uid] for uid in uids if uid in by_uid]


def _keyword_overlap(paper_text: str, query: str) -> bool:
    """Return True if any query token appears in the paper text (case-insensitive)."""
    tokens = [t.strip().lower() for t in query.split() if len(t.strip()) > 2]
    text_lower = paper_text.lower()
    return any(tok in text_lower for tok in tokens)


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    """Rank papers against the supplied SearchRequest.

    In demo mode: uses seeded ophthalmology fixtures.
    In live mode: fetches from all databases, extracts via LLM, normalizes, and ranks.
    """
    if settings.APP_MODE == "demo":
        from app.demo.fixtures import get_all_demo_triples

        triples = get_all_demo_triples()

        query_tokens = [t.strip().lower() for t in request.query.split() if len(t.strip()) > 2]
        if query_tokens:
            filtered = [
                (p, e, n)
                for p, e, n in triples
                if _keyword_overlap(
                    (p.title or "") + " " + (p.abstract or "") + " " + " ".join(p.keywords),
                    request.query,
                )
            ]
            if not filtered:
                filtered = triples
        else:
            filtered = triples

        ranked = await rank_papers(filtered, request)
        return SearchResponse(
            results=ranked,
            total=len(ranked),
            mode="demo",
            query=request.query,
        )

    # ── Live pipeline ────────────────────────────────────────────────────
    from app.services.pool import search_all_sources
    from app.services.extraction import extract_paper
    from app.services.triage import triage_papers
    from app.services import db

    run_id = str(uuid.uuid4())
    started_at = datetime.now(tz=timezone.utc)
    counts = StageCounts()
    relevance_cache: dict[str, tuple[float, dict]] = {}

    routing = get_routing(request)
    logger.info(
        "Live search [{}]: intent={}, sources={}, query={!r}, pool_size={}, max_results={}",
        run_id,
        routing.intent.value,
        sorted(routing.enabled_sources),
        request.query,
        request.pool_size,
        request.max_results,
    )

    pool_result = await search_all_sources(
        request.query,
        request.target_product,
        request.pool_size,
        keywords=request.keywords or None,
        min_year=request.min_year,
        max_year=request.max_year,
        country=request.country,
        enabled_sources=routing.enabled_sources,
        budget_overrides=routing.budget_overrides,
    )
    papers = pool_result.papers
    counts.pool_per_source = pool_result.source_counts
    counts.pool_total = sum(pool_result.source_counts.values())
    counts.post_dedup = len(papers)

    if not papers:
        return SearchResponse(
            results=[], total=0, mode="live", query=request.query,
            run_id=run_id, stage_counts=counts,
        )

    db.save_papers(papers)

    # Post-retrieval filters (journal, author, include/exclude terms)
    papers = apply_post_filters(papers, request)
    if not papers:
        return SearchResponse(
            results=[], total=0, mode="live", query=request.query,
            run_id=run_id, stage_counts=counts,
        )

    shortlisted = await triage_papers(
        papers,
        request.query,
        request.target_product,
        request.max_results,
        metrics_of_interest=request.metrics_of_interest or None,
    )
    papers = _papers_in_uid_order(papers, shortlisted)
    counts.post_triage = len(papers)

    if not papers:
        return SearchResponse(
            results=[], total=0, mode="live", query=request.query,
            run_id=run_id, stage_counts=counts,
        )

    metrics_hints = request.metrics_of_interest or []
    bypass_extraction_cache = len(metrics_hints) > 0

    triples = []
    for paper in papers:
        uid = paper.uid
        if not uid:
            continue

        fresh_extraction = False
        extraction = None if bypass_extraction_cache else db.load_extraction(uid)
        if extraction is None:
            extraction, llm_raw = await asyncio.gather(
                extract_paper(paper, metrics_of_interest=metrics_hints or None),
                llm_relevance_raw(paper, request),
            )
            db.save_extraction(uid, extraction)
            fresh_extraction = True
        else:
            llm_raw = await llm_relevance_raw(paper, request)

        r_pre = merge_relevance_llm(llm_raw, paper, extraction, request)
        relevance_cache[uid] = r_pre

        normalized = None if fresh_extraction else db.load_normalization(uid)
        if normalized is None:
            normalized = normalize_extraction(extraction)
            db.save_normalization(uid, normalized)

        triples.append((paper, extraction, normalized))

    counts.post_extraction = len(triples)

    ranked = await rank_papers(triples, request, relevance_cache=relevance_cache)
    counts.final_ranked = len(ranked)

    finished_at = datetime.now(tz=timezone.utc)
    run_log = RetrievalRunLog(
        run_id=run_id,
        query=request.query,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        mode="live",
        stage_counts=counts,
    )
    try:
        db.save_run_log(run_log)
    except Exception as exc:
        logger.warning("Failed to persist run log {}: {}", run_id, exc)

    return SearchResponse(
        results=ranked,
        total=len(ranked),
        mode="live",
        query=request.query,
        run_id=run_id,
        stage_counts=counts,
    )


# ── SSE helpers ──────────────────────────────────────────────────────────────

def _sse(event: str, data: dict) -> str:
    """Format a single SSE message."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _evidence_summary(study) -> str:
    """Short evidence descriptor: study type + sample size."""
    label = study.study_type.value.replace("_", " ")
    n = study.sample_size.value if study.sample_size is not None else None
    return f"{label}, n={n}" if n else label


async def _stream_search(request: SearchRequest) -> AsyncGenerator[str, None]:
    """Core generator that drives the streaming search pipeline."""
    from app.services.pool import (
        _dedupe_new_batch,
        _display_source,
        iter_pool_sources,
    )
    from app.services.extraction import extract_paper
    from app.services.triage import triage_papers_stream
    from app.services import db

    run_id = str(uuid.uuid4())
    started_at = datetime.now(tz=timezone.utc)
    counts = StageCounts()
    routing = get_routing(request)

    yield _sse("status", {
        "message": "Searching all databases…",
        "phase": "searching",
        "run_id": run_id,
        "intent": routing.intent.value,
    })

    seen_uids: set[str] = set()
    seen_dois: set[str] = set()
    papers: list[Paper] = []
    source_counts: dict[str, int] = {}

    try:
        async for label, batch, dt_ms in iter_pool_sources(
            request.query,
            request.target_product,
            request.pool_size,
            keywords=request.keywords or None,
            min_year=request.min_year,
            max_year=request.max_year,
            country=request.country,
            enabled_sources=routing.enabled_sources,
            budget_overrides=routing.budget_overrides,
        ):
            ck = "PubMed" if label == "PubMed_supplementary" else label
            source_counts[ck] = source_counts.get(ck, 0) + len(batch)
            new_batch = _dedupe_new_batch(batch, seen_uids, seen_dois)
            papers.extend(new_batch)

            pool_rows = [
                {"pmid": p.uid, "title": (p.title or "")[:120], "source": p.source}
                for p in new_batch
            ]
            yield _sse(
                "pool",
                {
                    "source": _display_source(label),
                    "source_key": label,
                    "duration_ms": round(dt_ms),
                    "paper_count": len(new_batch),
                    "papers": pool_rows,
                },
            )
            await asyncio.sleep(0)

    except Exception as exc:
        logger.error("Multi-source search failed: {}", exc)
        yield _sse("error", {"message": f"Search error: {exc}", "fatal": True})
        yield _sse("done", {"total": 0, "results": [], "mode": "live", "run_id": run_id})
        return

    pool_result_source_counts = source_counts
    counts.pool_per_source = pool_result_source_counts
    counts.pool_total = sum(pool_result_source_counts.values())
    counts.post_dedup = len(papers)

    if not papers:
        yield _sse("status", {"message": "No results found.", "phase": "done"})
        yield _sse("done", {"total": 0, "results": [], "mode": "live", "run_id": run_id})
        return

    db.save_papers(papers)

    # Post-retrieval filters
    papers = apply_post_filters(papers, request)
    if not papers:
        yield _sse("status", {"message": "No results after filtering.", "phase": "done"})
        yield _sse("done", {"total": 0, "results": [], "mode": "live", "run_id": run_id})
        return

    pool_total = len(papers)

    yield _sse("status", {
        "message": (
            f"Found {pool_total} result{'s' if pool_total != 1 else ''} "
            f"from {len([v for v in pool_result_source_counts.values() if v])} databases. "
            f"Selecting top {request.max_results} with AI…"
        ),
        "phase": "triaging",
        "pool_total": pool_total,
        "max_results": request.max_results,
        "source_counts": pool_result_source_counts,
    })

    by_uid_title = {p.uid: (p.title or "")[:120] for p in papers}
    try:
        shortlisted: list[str] = []
        accept_idx = 0
        async for uid in triage_papers_stream(
            papers,
            request.query,
            request.target_product,
            request.max_results,
            metrics_of_interest=request.metrics_of_interest or None,
        ):
            shortlisted.append(uid)
            accept_idx += 1
            yield _sse(
                "accept",
                {
                    "pmid": uid,
                    "index": accept_idx,
                    "title": by_uid_title.get(uid, ""),
                },
            )
        papers = _papers_in_uid_order(papers, shortlisted)
        counts.post_triage = len(papers)
    except Exception as exc:
        logger.error("Triage failed: {}", exc)
        yield _sse("error", {"message": f"Triage error: {exc}", "fatal": True})
        yield _sse("done", {"total": 0, "results": [], "mode": "live", "run_id": run_id})
        return

    if not papers:
        yield _sse("status", {"message": "No papers after triage.", "phase": "done"})
        yield _sse("done", {"total": 0, "results": [], "mode": "live", "run_id": run_id})
        return

    total = len(papers)
    yield _sse("status", {
        "message": f"Triage complete — extracting {total} paper{'s' if total != 1 else ''}…",
        "phase": "extracting",
        "total": total,
        "pool_total": pool_total,
    })

    metrics_hints = request.metrics_of_interest or []
    bypass_extraction_cache = len(metrics_hints) > 0

    triples = []
    processed = 0
    relevance_cache: dict[str, tuple[float, dict]] = {}

    for idx, paper in enumerate(papers, 1):
        uid = paper.uid
        if not uid:
            continue

        yield _sse("progress", {
            "current": idx,
            "total": total,
            "pmid": uid,
            "title": (paper.title or "")[:80],
            "phase": "extracting",
        })

        try:
            fresh_extraction = False
            extraction = None if bypass_extraction_cache else db.load_extraction(uid)
            if extraction is None:
                extraction, llm_raw = await asyncio.gather(
                    extract_paper(paper, metrics_of_interest=metrics_hints or None),
                    llm_relevance_raw(paper, request),
                )
                db.save_extraction(uid, extraction)
                fresh_extraction = True
            else:
                llm_raw = await llm_relevance_raw(paper, request)

            r_pre = merge_relevance_llm(llm_raw, paper, extraction, request)
            relevance_cache[uid] = r_pre

            normalized = None if fresh_extraction else db.load_normalization(uid)
            if normalized is None:
                normalized = normalize_extraction(extraction)
                db.save_normalization(uid, normalized)

            triples.append((paper, extraction, normalized))
            processed += 1

            composite, details = await score_composite(
                paper, extraction, normalized, request, r_precomputed=r_pre,
            )

            yield _sse("result", {
                "pmid": paper.pmid or uid,
                "doi": paper.doi,
                "title": paper.title,
                "abstract": paper.abstract,
                "journal": paper.journal,
                "published_date": paper.published_date.isoformat() if paper.published_date else None,
                "source": paper.source,
                "rank": processed,
                "composite_score": round(composite, 4),
                "relevance_score": round(details["scores"]["R"], 4),
                "product_similarity_score": round(details["scores"]["P"], 4),
                "metric_favorability_score": round(details["scores"]["M"], 4),
                "evidence_quality_score": round(details["scores"]["E"], 4),
                "evidence_breakdown": details["breakdowns"].get("E"),
                "metric_favorability_breakdown": details["breakdowns"].get("M"),
                "weights_used": details["weights_used"],
                "dimensions_excluded": details["dimensions_excluded"],
                "metric_score_estimated": details["metric_score_estimated"],
                "metric_score_incomplete": details["metric_score_incomplete"],
                "evidence_score_estimated": details["evidence_score_estimated"],
                "ranking_rationale": details["ranking_rationale"],
                "extracted_metrics": [m.model_dump(mode="json") for m in (extraction.metrics or [])],
                "relevance_label": (
                    extraction.topical_relevance.label.value
                    if extraction.topical_relevance else None
                ),
                "product_label": format_product_table_label(normalized),
                "evidence_label": _evidence_summary(extraction.study),
            })

        except Exception as exc:
            logger.error("Extraction failed for {}: {}", uid, exc)
            yield _sse("error", {"pmid": uid, "message": str(exc)})

    counts.post_extraction = len(triples)
    final_results = await rank_papers(triples, request, relevance_cache=relevance_cache)
    counts.final_ranked = len(final_results)

    finished_at = datetime.now(tz=timezone.utc)
    run_log = RetrievalRunLog(
        run_id=run_id,
        query=request.query,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=int((finished_at - started_at).total_seconds() * 1000),
        mode="live",
        stage_counts=counts,
    )
    try:
        db.save_run_log(run_log)
    except Exception as exc:
        logger.warning("Failed to persist run log {}: {}", run_id, exc)

    yield _sse("done", {
        "total": len(final_results),
        "results": [r.model_dump(mode="json") for r in final_results],
        "mode": "live",
        "run_id": run_id,
        "stage_counts": counts.model_dump(),
    })


@router.post("/search/stream")
async def search_stream(request: SearchRequest) -> StreamingResponse:
    """Streaming SSE endpoint — emits progress + per-paper results as they complete."""
    if settings.APP_MODE == "demo":
        from app.demo.fixtures import get_all_demo_triples

        async def _demo_stream() -> AsyncGenerator[str, None]:
            triples = get_all_demo_triples()
            yield _sse("status", {"message": "Demo mode — using fixtures", "phase": "demo", "total": len(triples)})
            ranked = await rank_papers(triples, request)
            yield _sse("done", {
                "total": len(ranked),
                "results": [r.model_dump(mode="json") for r in ranked],
                "mode": "demo",
            })

        return StreamingResponse(
            _demo_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return StreamingResponse(
        _stream_search(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
