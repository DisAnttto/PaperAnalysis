"""Direct service-level gold regression (no HTTP server).

Per gold case in ``tests/collection/cases.json``:

1. PubMed pool + triage: built query returns a pool containing golden PMIDs,
   and triage keeps them in the top-``max_results`` shortlist.
2. Single-paper score: fetch only the golden paper, LLM-extract + relevance,
   normalize, composite score vs ``min_composite_by_pmid``.

Gated by ``RUN_GOLD_PIPELINE=1`` (NCBI + LLM credentials in ``.env``).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from app.normalization import normalize_extraction
from app.ranking.composite import score_composite
from app.ranking.relevance_agent import llm_relevance_raw, merge_relevance_llm
from app.services.extraction import extract_paper
from app.services.pubmed import build_pubmed_query, fetch_papers, search_pmids
from app.services.triage import triage_papers
from tests.collection import get_case, load_cases

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_GOLD_PIPELINE"),
    reason="Set RUN_GOLD_PIPELINE=1 with PubMed + LLM keys in .env.",
)


def _case_ids() -> list[str]:
    return [c.id for c in load_cases()]


async def _golden_pmid_survives_triage(case_id: str) -> None:
    case = get_case(case_id)
    assert case is not None
    req = case.request
    exp = case.expectations
    assert exp.golden_pmids, f"case {case_id} has no golden_pmids"

    pubmed_term = build_pubmed_query(
        req.query,
        req.target_product,
        req.keywords or None,
    )
    pmids = await search_pmids(
        pubmed_term,
        max_results=req.pool_size,
        min_year=req.min_year,
        max_year=req.max_year,
        country=req.country,
    )
    pool_set = set(pmids)
    missing_pool = [g for g in exp.golden_pmids if g not in pool_set]
    assert not missing_pool, (
        f"Golden PMIDs not in PubMed pool for {case_id}: {missing_pool}; "
        f"term={pubmed_term[:400]!r}"
    )

    papers = await fetch_papers(pmids)
    assert papers, "fetch_papers returned empty"

    shortlisted = await triage_papers(
        papers,
        req.query,
        req.target_product,
        req.max_results,
    )
    short_set = set(shortlisted)
    missing_triage = [g for g in exp.golden_pmids if g not in short_set]
    assert not missing_triage, (
        f"Golden PMIDs not in triage shortlist for {case_id}: {missing_triage}; "
        f"shortlist={shortlisted}"
    )


@pytest.mark.parametrize("case_id", _case_ids())
def test_golden_pmid_survives_triage(case_id: str) -> None:
    asyncio.run(_golden_pmid_survives_triage(case_id))


async def _golden_paper_scoring(case_id: str) -> None:
    case = get_case(case_id)
    assert case is not None
    req = case.request
    exp = case.expectations
    thresholds = exp.min_composite_by_pmid
    assert thresholds, f"case {case_id} has no min_composite_by_pmid"

    metrics_hints = list(req.metrics_of_interest or [])

    for pmid, min_c in thresholds.items():
        papers = await fetch_papers([pmid])
        assert papers and papers[0].pmid == pmid, f"Failed to fetch PMID {pmid}"
        paper = papers[0]

        extraction, llm_raw = await asyncio.gather(
            extract_paper(paper, metrics_of_interest=metrics_hints or None),
            llm_relevance_raw(paper, req),
        )
        r_pre = merge_relevance_llm(llm_raw, paper, extraction, req)
        normalized = normalize_extraction(extraction)
        composite, details = await score_composite(
            paper,
            extraction,
            normalized,
            req,
            r_precomputed=r_pre,
        )

        assert composite >= float(min_c), (
            f"{case_id} PMID {pmid}: composite {composite:.4f} < {min_c}; "
            f"scores={details.get('scores')}; "
            f"dimensions_excluded={details.get('dimensions_excluded')}; "
            f"breakdown_keys={list((details.get('breakdowns') or {}).keys())}"
        )


@pytest.mark.parametrize("case_id", _case_ids())
def test_golden_paper_scoring(case_id: str) -> None:
    asyncio.run(_golden_paper_scoring(case_id))
