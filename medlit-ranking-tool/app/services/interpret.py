"""Outcome interpretation orchestrator.

Two-tier LLM strategy:
  Heavy model (get_llm_client_config) — angle generation, overall synthesis
  Light model (get_llm_light_config)  — novel-angle query generation, per-angle summaries

Step 2 implements: claim templates, search dispatch, relevance scoring, grouping, orchestrator wiring.
Step 3 implements: _generate_angles, _generate_angle_summary, _generate_overall_summary (LLM prompts).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from openai import AsyncOpenAI

from app.core.config import get_llm_extra_request_kwargs, get_llm_light_config
from app.models.extraction import ExtractionResult
from app.models.interpret import (
    ClaimResult,
    EvidenceClaim,
    EvidencePackage,
    InterpretationAngle,
    InterpretRequest,
    InterpretResponse,
    ObservedFinding,
)
from app.models.paper import Paper
from app.models.search import SearchRequest, TargetProductProfile
from app.normalization import normalize_extraction
from app.ranking.composite import rank_papers
from app.ranking.metric_favorability import _metric_name_matches
from app.ranking.relevance_agent import llm_relevance_raw, merge_relevance_llm
from app.services.extraction import extract_paper
from app.services.pool import search_all_sources
from app.services.triage import triage_papers

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Claim decomposition templates
# ---------------------------------------------------------------------------

def _context_term(finding: ObservedFinding) -> str:
    """Best single context term for building query strings."""
    return finding.procedure or finding.product_name or finding.clinical_context or ""


def _template_transient_recovery(
    angle: InterpretationAngle, finding: ObservedFinding, idx: int
) -> list[EvidenceClaim]:
    ctx = _context_term(finding)
    ctx_clause = f' AND "{ctx}"' if ctx else ""
    query = (
        f'"{finding.metric_name}" AND '
        f'("transient" OR "resolved" OR "normalized" OR "recovery" OR "spike")'
        f"{ctx_clause}"
    )
    return [EvidenceClaim(
        claim_id=f"{angle.angle_id}_{idx}",
        angle_id=angle.angle_id,
        claim_text=f"{finding.metric_name} elevation at {finding.timepoint or 'early timepoint'} "
                   f"is transient and resolves over time.",
        search_query=query,
        metric_filter=finding.metric_name,
        timepoint_filter=finding.timepoint,
    )]


def _template_value_precedent(
    angle: InterpretationAngle, finding: ObservedFinding, idx: int
) -> list[EvidenceClaim]:
    ctx = _context_term(finding)
    ctx_clause = f' AND "{ctx}"' if ctx else ""
    # Neighbouring integer values ±2 for exact-value queries
    v = finding.observed_value
    nearby = " OR ".join(
        f'"{int(n)}"' for n in [v - 2, v - 1, v, v + 1, v + 2] if n >= 0
    )
    tp = finding.timepoint or ""
    tp_clause = f' AND "{tp}"' if tp else ""
    query = (
        f'"{finding.metric_name}"{tp_clause} AND ({nearby}){ctx_clause}'
    )
    return [EvidenceClaim(
        claim_id=f"{angle.angle_id}_{idx}",
        angle_id=angle.angle_id,
        claim_text=f"Published studies report {finding.metric_name} values near "
                   f"{finding.observed_value} {finding.metric_unit or ''} "
                   f"at similar timepoints.",
        search_query=query,
        value_range=(max(0.0, v - 2.0), v + 2.0),
        metric_filter=finding.metric_name,
        timepoint_filter=finding.timepoint,
    )]


def _template_acceptable_range(
    angle: InterpretationAngle, finding: ObservedFinding, idx: int
) -> list[EvidenceClaim]:
    ctx = _context_term(finding)
    ctx_clause = f' AND "postoperative"' if not ctx else f' AND "{ctx}"'
    query_range = (
        f'"{finding.metric_name}" AND '
        f'("safe" OR "acceptable" OR "normal range" OR "within normal" OR "threshold")'
        f"{ctx_clause}"
    )
    query_threshold = (
        f'"{finding.metric_name}" AND '
        f'("intervention threshold" OR "treatment threshold" OR "clinical threshold")'
    )
    v = finding.observed_value
    return [
        EvidenceClaim(
            claim_id=f"{angle.angle_id}_{idx}_a",
            angle_id=angle.angle_id,
            claim_text=f"A {finding.metric_name} of {finding.observed_value} "
                       f"{finding.metric_unit or ''} is within a safe/acceptable range.",
            search_query=query_range,
            value_range=(max(0.0, v - 5.0), v + 5.0),
            metric_filter=finding.metric_name,
        ),
        EvidenceClaim(
            claim_id=f"{angle.angle_id}_{idx}_b",
            angle_id=angle.angle_id,
            claim_text=f"Known clinical intervention thresholds for {finding.metric_name}.",
            search_query=query_threshold,
            metric_filter=finding.metric_name,
        ),
    ]


def _template_statistical_not_clinical(
    angle: InterpretationAngle, finding: ObservedFinding, idx: int
) -> list[EvidenceClaim]:
    ctx = finding.clinical_context or _context_term(finding)
    ctx_clause = f' AND "{ctx}"' if ctx else ""
    query = (
        f'"{finding.metric_name}" AND '
        f'("clinically significant" OR "minimal clinically important difference" '
        f'OR "MCID" OR "clinical relevance" OR "clinical significance")'
        f"{ctx_clause}"
    )
    return [EvidenceClaim(
        claim_id=f"{angle.angle_id}_{idx}",
        angle_id=angle.angle_id,
        claim_text=f"The observed {finding.metric_name} difference is statistically "
                   f"significant but may not be clinically meaningful.",
        search_query=query,
        metric_filter=finding.metric_name,
    )]


def _template_risk_signal(
    angle: InterpretationAngle, finding: ObservedFinding, idx: int
) -> list[EvidenceClaim]:
    ctx = _context_term(finding)
    ctx_clause = f' AND "{ctx}"' if ctx else ""
    query = (
        f'"{finding.metric_name}" AND '
        f'("adverse" OR "complication" OR "risk factor" OR "safety concern" OR "harm")'
        f"{ctx_clause}"
    )
    return [EvidenceClaim(
        claim_id=f"{angle.angle_id}_{idx}",
        angle_id=angle.angle_id,
        claim_text=f"Elevated {finding.metric_name} may represent a genuine safety signal.",
        search_query=query,
        metric_filter=finding.metric_name,
        timepoint_filter=finding.timepoint,
    )]


def _template_mechanism_expected(
    angle: InterpretationAngle, finding: ObservedFinding, idx: int
) -> list[EvidenceClaim]:
    ctx = _context_term(finding)
    ctx_clause = f' AND "{ctx}"' if ctx else ""
    query = (
        f'"{finding.metric_name}" AND '
        f'("expected" OR "mechanism" OR "physiological" OR "postoperative course" '
        f'OR "normal response")'
        f"{ctx_clause}"
    )
    return [EvidenceClaim(
        claim_id=f"{angle.angle_id}_{idx}",
        angle_id=angle.angle_id,
        claim_text=f"The {finding.metric_name} change is an expected physiological "
                   f"response to the procedure/product.",
        search_query=query,
        metric_filter=finding.metric_name,
        timepoint_filter=finding.timepoint,
    )]


_CLAIM_TEMPLATES: dict[
    str,
    "Callable[[InterpretationAngle, ObservedFinding, int], list[EvidenceClaim]]",
] = {
    "transient_recovery": _template_transient_recovery,
    "value_precedent": _template_value_precedent,
    "acceptable_range": _template_acceptable_range,
    "statistical_not_clinical": _template_statistical_not_clinical,
    "risk_signal": _template_risk_signal,
    "mechanism_expected": _template_mechanism_expected,
}


# ---------------------------------------------------------------------------
# Light-model fallback for novel angles
# ---------------------------------------------------------------------------

async def _novel_angle_query(angle: InterpretationAngle, finding: ObservedFinding) -> str:
    """Use the Light model to generate a search query for an unrecognised angle."""
    cfg = get_llm_light_config()
    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    extra = get_llm_extra_request_kwargs()
    system = (
        "You are a medical literature search specialist. "
        "Given a clinical interpretation angle and an observed finding, "
        "return ONLY a PubMed-style boolean search query string. "
        "No explanation, no markdown, just the query."
    )
    user = (
        f"Angle: {angle.label} — {angle.description}\n"
        f"Finding: {finding.metric_name} = {finding.observed_value} "
        f"{finding.metric_unit or ''} at {finding.timepoint or 'unspecified timepoint'}, "
        f"context: {finding.clinical_context or finding.procedure or finding.product_name or 'general'}"
    )
    resp = await client.chat.completions.create(
        model=cfg.model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.1,
        max_tokens=256,
        **extra,
    )
    return (resp.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# Claim decomposition
# ---------------------------------------------------------------------------

async def _decompose_claims(
    angles: list[InterpretationAngle],
    finding: ObservedFinding,
) -> list[EvidenceClaim]:
    """Decompose interpretation angles into concrete evidence claims.

    Known angles use deterministic templates.  Novel angles fall back to
    the Light model for query generation (one call per novel angle).
    """
    all_claims: list[EvidenceClaim] = []
    novel_tasks: list[tuple[int, InterpretationAngle]] = []

    for idx, angle in enumerate(angles):
        template_fn = _CLAIM_TEMPLATES.get(angle.angle_id)
        if template_fn is not None:
            all_claims.extend(template_fn(angle, finding, idx))
        else:
            novel_tasks.append((idx, angle))

    # Resolve novel angles in parallel
    if novel_tasks:
        queries = await asyncio.gather(
            *[_novel_angle_query(angle, finding) for _, angle in novel_tasks],
            return_exceptions=True,
        )
        for (idx, angle), result in zip(novel_tasks, queries):
            query = (
                result if isinstance(result, str)
                else f'"{finding.metric_name}" AND "{_context_term(finding)}"'
            )
            all_claims.append(EvidenceClaim(
                claim_id=f"{angle.angle_id}_{idx}",
                angle_id=angle.angle_id,
                claim_text=angle.description,
                search_query=query,
                metric_filter=finding.metric_name,
                timepoint_filter=finding.timepoint,
            ))

    return all_claims


# ---------------------------------------------------------------------------
# Claim-relevance scoring (deterministic, no LLM)
# ---------------------------------------------------------------------------

def _score_claim_relevance(
    claim: EvidenceClaim,
    pairs: list[tuple[Paper, ExtractionResult]],
) -> dict[str, float]:
    """Score each paper's relevance to the specific claim.

    Uses three deterministic signals:
      1. Metric name match (fuzzy, via existing _metric_name_matches)
      2. Value in claim.value_range
      3. Timepoint overlap (substring)
    Returns a uid -> score (0–1) mapping.
    """
    scores: dict[str, float] = {}
    for paper, ext in pairs:
        # Use pmid > doi > title as lookup key — mirrors RankedPaperResponse fields
        uid = paper.pmid or paper.doi or paper.title
        s = 0.0
        n = 0

        metrics = ext.metrics or []

        if claim.metric_filter:
            n += 1
            if any(
                _metric_name_matches(claim.metric_filter, m.metric_name or "")
                for m in metrics
            ):
                s += 1.0

        if claim.value_range:
            lo, hi = claim.value_range
            n += 1
            if any(
                lo <= (m.numeric_value or 0.0) <= hi
                for m in metrics
                if m.numeric_value is not None
            ):
                s += 1.0

        if claim.timepoint_filter:
            tp = claim.timepoint_filter.lower()
            n += 1
            if any(tp in (m.timepoint or "").lower() for m in metrics):
                s += 1.0

        scores[uid] = s / max(n, 1)
    return scores


# ---------------------------------------------------------------------------
# Per-claim search pipeline
# ---------------------------------------------------------------------------

def _papers_by_uid(papers: list[Paper], uids: list[str]) -> list[Paper]:
    by_uid = {p.uid: p for p in papers}
    return [by_uid[uid] for uid in uids if uid in by_uid]


async def _run_claim_search(
    claim: EvidenceClaim,
    request: InterpretRequest,
) -> ClaimResult:
    """Run the full search pipeline for a single evidence claim.

    Pool → triage → extract + normalize → rank → score claim-relevance.
    """
    query = claim.search_query
    target_product: TargetProductProfile | None = request.target_product

    pool_result = await search_all_sources(query, target_product, request.pool_size)
    papers = pool_result.papers
    if not papers:
        return ClaimResult(claim=claim, papers=[], claim_relevance_scores={})

    shortlisted_uids = await triage_papers(
        papers,
        query,
        target_product,
        request.max_results_per_angle,
    )
    shortlisted = _papers_by_uid(papers, shortlisted_uids)
    if not shortlisted:
        return ClaimResult(claim=claim, papers=[], claim_relevance_scores={})

    # Build a minimal SearchRequest for rank_papers (only query is required)
    search_req = SearchRequest(
        query=query,
        target_product=target_product,
        max_results=len(shortlisted),
        pool_size=max(len(shortlisted), 1),
    )

    relevance_cache: dict[str, tuple[float, dict]] = {}
    pairs: list[tuple[Paper, ExtractionResult]] = []
    triples = []

    for paper in shortlisted:
        extraction = await extract_paper(
            paper,
            metrics_of_interest=[claim.metric_filter] if claim.metric_filter else None,
        )
        llm_raw = await llm_relevance_raw(paper, search_req)
        r_pre = merge_relevance_llm(llm_raw, paper, extraction, search_req)
        relevance_cache[paper.uid] = r_pre
        normalized = normalize_extraction(extraction)
        pairs.append((paper, extraction))
        triples.append((paper, extraction, normalized))

    ranked = await rank_papers(triples, search_req, relevance_cache=relevance_cache)
    scores = _score_claim_relevance(claim, pairs)
    return ClaimResult(claim=claim, papers=ranked, claim_relevance_scores=scores)


# ---------------------------------------------------------------------------
# Grouping into evidence packages
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _group_into_packages(
    angles: list[InterpretationAngle],
    claim_results: list[ClaimResult],
) -> list[EvidencePackage]:
    """Group claim results by angle and compute aggregate strength.

    Within each claim's paper list, papers are re-sorted by:
      0.5 * claim_relevance + 0.3 * evidence_quality + 0.2 * composite_score
    """
    by_angle: dict[str, list[ClaimResult]] = defaultdict(list)
    for cr in claim_results:
        by_angle[cr.claim.angle_id].append(cr)

    packages: list[EvidencePackage] = []
    for angle in angles:
        claims = by_angle.get(angle.angle_id, [])

        # Re-sort papers within each claim by claim-blended score
        for cr in claims:
            rel_scores = cr.claim_relevance_scores
            cr.papers.sort(
                key=lambda p: (
                    0.5 * rel_scores.get(p.pmid or p.doi or p.title, 0.0)
                    + 0.3 * p.evidence_quality_score
                    + 0.2 * p.composite_score
                ),
                reverse=True,
            )

        all_relevance = [
            s for cr in claims for s in cr.claim_relevance_scores.values()
        ]
        strength = _mean(all_relevance)

        packages.append(EvidencePackage(
            angle=angle,
            claims=claims,
            strength=strength,
            summary="",  # filled by Step 3 (_generate_angle_summary)
        ))

    return packages


# ---------------------------------------------------------------------------
# LLM stubs — replaced by Step 3
# ---------------------------------------------------------------------------

async def _generate_angles(finding: ObservedFinding) -> list[InterpretationAngle]:
    """Placeholder: returns 3 generic angles so the orchestrator is testable.

    Step 3 replaces this with a real HEAVY-model LLM call.
    """
    ctx = _context_term(finding)
    return [
        InterpretationAngle(
            angle_id="value_precedent",
            label="Value Precedent",
            description=f"Published studies report similar {finding.metric_name} values.",
            reasoning="Placeholder — Step 3 implements LLM angle generation.",
        ),
        InterpretationAngle(
            angle_id="acceptable_range",
            label="Acceptable Range",
            description=f"{finding.metric_name} is within a safe/acceptable threshold.",
            reasoning="Placeholder — Step 3 implements LLM angle generation.",
        ),
        InterpretationAngle(
            angle_id="transient_recovery",
            label="Transient Recovery",
            description=f"The {finding.metric_name} elevation is transient and resolves.",
            reasoning="Placeholder — Step 3 implements LLM angle generation.",
        ),
    ]


async def _generate_angle_summary(package: EvidencePackage) -> str:
    """Placeholder: returns empty string.  Step 3 implements LIGHT-model summary."""
    return ""


async def _generate_overall_summary(
    finding: ObservedFinding,
    packages: list[EvidencePackage],
) -> str:
    """Placeholder: returns empty string.  Step 3 implements HEAVY-model synthesis."""
    return ""


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def interpret_finding(request: InterpretRequest) -> InterpretResponse:
    """End-to-end interpretation pipeline.

    1. HEAVY: generate interpretation angles from the finding (Step 3 LLM call)
    2. Templates + LIGHT: decompose angles into concrete evidence claims
    3. Parallel: run search pipeline for each claim (semaphore-limited)
    4. Deterministic: group into evidence packages, score relevance
    5. LIGHT: per-angle summary; HEAVY: overall synthesis (Step 3 LLM calls)
    """
    angles = await _generate_angles(request.finding)

    claims = await _decompose_claims(angles, request.finding)
    if not claims:
        return InterpretResponse(
            finding=request.finding,
            angles=[],
            overall_summary="No evidence claims could be generated.",
        )

    sem = asyncio.Semaphore(4)

    async def _guarded(c: EvidenceClaim) -> ClaimResult:
        async with sem:
            try:
                return await _run_claim_search(c, request)
            except Exception as exc:
                logger.warning("Claim search failed for %s: %s", c.claim_id, exc)
                return ClaimResult(
                    claim=c,
                    papers=[],
                    claim_relevance_scores={},
                )

    claim_results = await asyncio.gather(*[_guarded(c) for c in claims])

    packages = _group_into_packages(angles, list(claim_results))

    for pkg in packages:
        pkg.summary = await _generate_angle_summary(pkg)

    overall = await _generate_overall_summary(request.finding, packages)

    return InterpretResponse(
        finding=request.finding,
        angles=packages,
        overall_summary=overall,
    )
