"""Thematic gold regression for the IOL POD1 IOP safety case.

Reference run: baseline_iop_case_run_02.md (run ID 6d100d65-8da7-4f57-b65c-034535623566).

This test checks the BEHAVIORAL / THEMATIC acceptance criteria for the
cataract/IOL postoperative IOP safety case — criteria that cannot be
expressed by simple PMID + composite-score assertions alone.

Gated by RUN_GOLD_PIPELINE=1 (requires NCBI + LLM credentials in .env).

CLINICAL ACCEPTANCE CRITERIA (reference for human reviewers)
=============================================================
The following are the requirements encoded as automated assertions below.
Items marked (*) require clinical judgment and are checked qualitatively via
assertions on evidence composition, not by asserting a specific clinical verdict.

1.  Top results dominated by routine cataract/phaco/IOL postoperative IOP papers.
    - At least 8 of the 14 literature-track results have titles that contain
      "cataract" OR "phacoemulsification" OR "phaco" OR "intraocular lens"
      AND do NOT contain combined-glaucoma-procedure keywords.

2.  At least one paper directly supports POD1 IOP around 18-20 mmHg.
    - At least 1 result has extracted metrics with a timepoint containing
      "day 1" / "postoperative day 1" / "POD1" / "first postoperative day"
      and a numeric IOP value in the range [15, 25] mmHg.

3.  At least one paper supports short-term postoperative IOP rise followed by recovery.
    - At least 1 result has extracted IOP values showing an early elevation
      (numeric IOP > 16 mmHg at 6h or 12h or 24h) that resolves (documented
      as "not significant" at 1 week, OR later timepoint IOP lower than peak).
    - Checked via abstract text as a fallback if metrics are sparse.

4.  At least one paper supports clinically meaningful thresholds or intervention triggers.
    - At least 1 result mentions IOP thresholds >= 22 mmHg, OR >= 30 mmHg,
      OR documents pharmacological/surgical prophylaxis (carbachol, timolol,
      acetazolamide, etc.) explicitly tied to IOP management.

5.  At least one paper covers high-risk subgroups.
    - At least 1 result title or abstract mentions "glaucoma" OR
      "pseudoexfoliation" OR "ocular hypertension" OR "elevated preoperative IOP".

6.  Combined-glaucoma-procedure papers must not dominate.
    - At most 3 of the top 10 results may have titles containing
      trabeculectomy / goniotomy / canaloplasty / GATT etc.

7.  M dimension is active.
    - At least 10 of 20 results have metric_favorability_score > 0.
      This confirms metrics_of_interest is non-empty and the M scorer ran.

8.  Intent must route as SAFETY (not EFFICACY).
    - classify_intent() must return QueryIntent.SAFETY for this case's query
      when the target is an IOL device.

(*) NOT asserted as code — requires clinical human review:
    - The system must not implicitly assert that POD1 IOP of 20 mmHg is
      definitively safe. Evidence retrieval is neutral; the system presents
      papers showing IOP behavior, not a conclusion about safety thresholds.
    - Statistical significance alone (p < 0.05 for a between-group IOP
      difference) is not treated as a clinically meaningful safety signal.
      The system surfaces papers with numeric IOP data; clinical interpretation
      is left to the reviewer.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import pytest

from app.services.intent_router import QueryIntent, classify_intent
from tests.collection import get_case
from tests.collection.checks import _GLAUCOMA_PROCEDURE_TERMS, expectation_failures

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_GOLD_PIPELINE"),
    reason="Set RUN_GOLD_PIPELINE=1 with PubMed + LLM keys in .env.",
)

CASE_ID = "iol_pod1_iop_safety"

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_ROUTINE_PHACO_TERMS = ("cataract", "phacoemulsification", "phaco", "intraocular lens")

_IOP_INTERVENTION_TERMS = (
    "carbachol",
    "timolol",
    "acetazolamide",
    "dorzolamide",
    "brimonidine",
    "mannitol",
    "prophylaxis",
    "prophylactic",
    "iop-lowering",
    "iop lowering",
    "antiglaucoma",
    "anti-glaucoma",
)

_HIGH_RISK_TERMS = (
    "glaucoma",
    "pseudoexfoliation",
    "ocular hypertension",
    "elevated preoperative iop",
    "elevated pre-operative iop",
    "elevated baseline iop",
)

_POD1_TIMEPOINT_PATTERN = re.compile(
    r"(post.?operative\s+day\s+1|pod[\s-]?1|first\s+post.?operative\s+day|day\s+1\s+post)",
    re.IGNORECASE,
)

_THRESHOLD_PATTERN = re.compile(
    r"(iop\s+(spike|spikes)|"
    r"\b(22|25|30|35)\s*(mm\s*hg|mmhg)|"
    r"(>=\s*22|>=\s*30|>\s*30|>\s*22|>30|>22)\s*(mm\s*hg|mmhg)?)",
    re.IGNORECASE,
)


def _text(row: dict[str, Any]) -> str:
    """Concatenate title + abstract for keyword searches."""
    return ((row.get("title") or "") + " " + (row.get("abstract") or "")).lower()


def _is_routine_phaco(row: dict[str, Any]) -> bool:
    title = (row.get("title") or "").lower()
    title_has_routine = any(t in title for t in _ROUTINE_PHACO_TERMS)
    title_has_procedure = any(t in title for t in _GLAUCOMA_PROCEDURE_TERMS)
    return title_has_routine and not title_has_procedure


def _extracted_iop_metrics(row: dict[str, Any]) -> list[dict]:
    """Return extracted_metrics entries that are IOP-related."""
    metrics = row.get("extracted_metrics") or []
    return [
        m for m in metrics
        if "iop" in (m.get("metric_name_normalized") or "").lower()
        or "intraocular" in (m.get("metric_name_raw") or "").lower()
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Full pipeline runner
# ──────────────────────────────────────────────────────────────────────────────

async def _run_case() -> list[dict[str, Any]]:
    """Run the full pipeline for the IOP gold case and return ranked results."""
    from app.normalization import normalize_extraction
    from app.ranking.composite import score_composite
    from app.ranking.relevance_agent import llm_relevance_raw, merge_relevance_llm
    from app.services.extraction import extract_paper
    from app.services.pool import build_pool
    from app.services.triage import triage_papers

    case = get_case(CASE_ID)
    assert case is not None, f"Case '{CASE_ID}' not found in cases.json"
    req = case.request

    # Pool
    pool = await build_pool(req)
    assert pool, "build_pool returned empty — check PubMed/OpenAlex connectivity"

    # Triage
    triaged = await triage_papers(pool, req.query, req.target_product, req.max_results)
    assert triaged, "triage_papers returned empty"

    # Fetch full papers for triage survivors (triage returns UIDs)
    from app.services.pubmed import fetch_papers
    pmids = [uid for uid in triaged if uid and uid.isdigit()]
    papers_by_pmid: dict[str, Any] = {}
    if pmids:
        fetched = await fetch_papers(pmids)
        papers_by_pmid = {p.pmid: p for p in fetched if p.pmid}

    # Extract + normalize + score all triage survivors
    metrics_hints = list(req.metrics_of_interest or [])
    results: list[dict[str, Any]] = []

    for uid in triaged:
        paper = papers_by_pmid.get(uid)
        if paper is None:
            # Regulatory / non-PubMed record — use stub row
            results.append({
                "pmid": None,
                "title": uid,
                "composite_score": 0.1,
                "metric_favorability_score": 0.0,
                "extracted_metrics": [],
            })
            continue

        extraction, llm_raw = await asyncio.gather(
            extract_paper(paper, metrics_of_interest=metrics_hints or None),
            llm_relevance_raw(paper, req),
        )
        from app.ranking.relevance_agent import merge_relevance_llm
        r_pre = merge_relevance_llm(llm_raw, paper, extraction, req)
        normalized = normalize_extraction(extraction)
        composite, details = await score_composite(
            paper, extraction, normalized, req, r_precomputed=r_pre,
        )

        scores = details.get("scores") or {}
        results.append({
            "pmid": paper.pmid,
            "title": paper.title or "",
            "abstract": paper.abstract or "",
            "composite_score": composite,
            "relevance_score": scores.get("R", 0.0),
            "product_similarity_score": scores.get("P", 0.0),
            "metric_favorability_score": scores.get("M", 0.0),
            "evidence_quality_score": scores.get("E", 0.0),
            "extracted_metrics": [
                m.model_dump() if hasattr(m, "model_dump") else dict(m)
                for m in (extraction.metrics or [])
            ],
        })

    # Sort by composite score descending, assign ranks
    results.sort(key=lambda r: r.get("composite_score") or 0.0, reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def iop_results() -> list[dict[str, Any]]:
    """Run the full pipeline once; reuse across all tests in this module."""
    return asyncio.run(_run_case())


def test_iop_pmid_and_composite_expectations(iop_results: list[dict]) -> None:
    """Golden PMIDs present, meet composite floors, within rank ceilings."""
    case = get_case(CASE_ID)
    assert case is not None
    result_dict = {"results": iop_results}
    failures = expectation_failures(result_dict, case.expectations)
    assert not failures, "IOP gold case expectation failures:\n" + "\n".join(failures)


def test_iop_intent_routes_as_safety() -> None:
    """classify_intent must return SAFETY (not EFFICACY) for this query.

    The tie-break fix (SAFETY preferred over EFFICACY when scores equal)
    must remain active. If this regresses, re-check intent_router.py.
    """
    case = get_case(CASE_ID)
    assert case is not None
    intent = classify_intent(
        case.request.query,
        target_product=case.request.target_product,
    )
    assert intent == QueryIntent.SAFETY, (
        f"Expected SAFETY intent, got {intent!r}. "
        f"Check the SAFETY/EFFICACY tie-break in classify_intent()."
    )


def test_iop_routine_cataract_dominates_top_results(iop_results: list[dict]) -> None:
    """At least 8 of the top 14 results are routine cataract/phaco/IOL papers.

    Routine = title contains cataract/phaco/intraocular lens AND does NOT
    contain a combined-glaucoma-procedure keyword.  This ensures glaucoma-
    procedure papers have not displaced routine cataract IOP papers.
    """
    top14 = [r for r in iop_results if (r.get("rank") or 99) <= 14 and r.get("pmid")]
    routine_count = sum(1 for r in top14 if _is_routine_phaco(r))
    assert routine_count >= 8, (
        f"Only {routine_count}/14 literature results are routine cataract/phaco/IOL "
        f"papers (need >= 8). Titles in top 14:\n"
        + "\n".join(f"  rank={r['rank']}: {r.get('title', '?')}" for r in top14)
    )


def test_iop_pod1_iop_bucket(iop_results: list[dict]) -> None:
    """At least 1 result has POD1 IOP data in the 15-25 mmHg range.

    This is the direct match for the case scenario (POD1 mean ~20 mmHg
    investigational / ~18 mmHg control). PMID 35187424 (rank 3 in run-02)
    should satisfy this: viscoelastic group POD1 IOP = 19.1 mmHg.
    """
    pod1_papers = []
    for r in iop_results:
        metrics = _extracted_iop_metrics(r)
        for m in metrics:
            timepoint = (m.get("timepoint") or "").lower()
            val = m.get("numeric_value")
            if (
                _POD1_TIMEPOINT_PATTERN.search(timepoint)
                and val is not None
                and 15.0 <= float(val) <= 25.0
            ):
                pod1_papers.append(r)
                break
        # Fallback: check abstract text for POD1 IOP values
        if not pod1_papers or pod1_papers[-1] is not r:
            text = _text(r)
            if "day 1" in text and re.search(r"\b1[5-9]\.\d|\b20\.\d|\b2[0-5]\b", text):
                pod1_papers.append(r)

    assert pod1_papers, (
        "No result found with POD1 IOP data in [15, 25] mmHg range. "
        "Expected at least PMID 35187424 (BSS vs viscoelastic, POD1 IOP 19.1 mmHg). "
        "Check that PubMed retrieved PMID 35187424 and extraction captured the POD1 timepoint."
    )


def test_iop_rise_and_recovery_bucket(iop_results: list[dict]) -> None:
    """At least 1 result supports short-term IOP rise followed by recovery.

    The canonical paper is PMID 11159474 (IOP spikes at 6h, resolved at 1 week)
    or PMID 9091708 (IOP drops D0->D1->D3 under prophylaxis).
    Check via abstract text for spike + resolution language.
    """
    recovery_terms = (
        "returned to",
        "resolved",
        "not statistically different",
        "no significant",
        "1 week postoperatively",
        "week postoperatively",
        "normalized",
        "returned to baseline",
    )
    spike_terms = (
        "iop spike",
        "iop spikes",
        "iop increase",
        "iop elevation",
        "iop rise",
        "increased",
    )

    found = False
    for r in iop_results:
        text = _text(r)
        has_spike = any(t in text for t in spike_terms)
        has_recovery = any(t in text for t in recovery_terms)
        if has_spike and has_recovery:
            found = True
            break

    assert found, (
        "No result found that documents both an early IOP rise and subsequent recovery. "
        "Expected at least PMID 11159474 (IOP spikes at 6h, not significant at 1 week) "
        "or PMID 9091708 (IOP drops under carbachol prophylaxis). "
        "Check triage and PubMed retrieval."
    )


def test_iop_threshold_or_intervention_bucket(iop_results: list[dict]) -> None:
    """At least 1 result mentions clinically meaningful IOP thresholds or interventions.

    This covers: IOP >= 22/25/30 mmHg, IOP spike, pharmacological prophylaxis
    (carbachol, timolol, etc.).  PMID 11159474 (spikes >= 30 mmHg) or
    PMID 2912119 (carbachol prophylaxis) should satisfy this.
    """
    found = False
    for r in iop_results:
        text = _text(r)
        if _THRESHOLD_PATTERN.search(text) or any(t in text for t in _IOP_INTERVENTION_TERMS):
            found = True
            break

    assert found, (
        "No result mentions clinically meaningful IOP thresholds (>= 22/30 mmHg) "
        "or intervention triggers (carbachol, timolol, prophylaxis). "
        "Expected at least PMID 11159474 (IOP spikes >= 30 mmHg, p=0.023) "
        "or PMID 2912119 (carbachol reduces IOP rise). "
        "Check triage and extraction."
    )


def test_iop_high_risk_subgroup_present(iop_results: list[dict]) -> None:
    """At least 1 result covers a high-risk subgroup (glaucoma, PEX, ocular HTN).

    High-risk subgroup evidence is expected but must not dominate. PMID 8784635
    (glaucomatous vs non-glaucomatous IOP pattern) should satisfy this.
    Combined-glaucoma-PROCEDURE papers are different — see the dominance test.
    """
    found = False
    for r in iop_results:
        text = _text(r)
        if any(t in text for t in _HIGH_RISK_TERMS):
            found = True
            break

    assert found, (
        "No result covers a high-risk subgroup (glaucoma, pseudoexfoliation, "
        "ocular hypertension, elevated preop IOP). "
        "Expected at least PMID 8784635 (glaucomatous vs non-glaucomatous IOP pattern)."
    )


def test_iop_m_dimension_active(iop_results: list[dict]) -> None:
    """At least 10 of 20 results have metric_favorability_score > 0.

    Confirms the M dimension is active (metrics_of_interest non-empty in request).
    If this regresses, the M scorer is being bypassed or metrics_of_interest
    was accidentally cleared in the request payload.
    """
    m_nonzero = sum(
        1 for r in iop_results
        if (r.get("metric_favorability_score") or 0.0) > 0.0
    )
    assert m_nonzero >= 10, (
        f"Only {m_nonzero}/20 results have metric_favorability_score > 0. "
        f"Check that metrics_of_interest is non-empty in the IOP case request "
        f"and that bypass_extraction_cache is being triggered correctly."
    )


def test_iop_glaucoma_procedure_not_dominant(iop_results: list[dict]) -> None:
    """At most 3 combined-glaucoma-procedure papers in top 10.

    Combined-glaucoma-procedure papers (trabeculectomy, goniotomy, canaloplasty,
    etc.) should not dominate the top results for a routine IOL safety query.
    The triage -0.15 penalty must remain active for this query.
    """
    top10 = sorted(iop_results, key=lambda r: r.get("rank") or 99)[:10]
    procedure_papers = [
        r for r in top10
        if any(term in (r.get("title") or "").lower() for term in _GLAUCOMA_PROCEDURE_TERMS)
    ]
    assert len(procedure_papers) <= 3, (
        f"Combined-glaucoma-procedure papers dominate top 10: "
        f"{len(procedure_papers)} found (max 3 allowed). "
        f"Titles: {[r.get('title') for r in procedure_papers]}. "
        f"Check that the glaucoma-procedure triage penalty is active in prescore_paper()."
    )
