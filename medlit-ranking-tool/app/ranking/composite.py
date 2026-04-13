"""Composite scoring and full ranking pipeline (ranking_spec §§3-4).

Assembles the four dimension scores, handles weight renormalisation when
dimensions are excluded, aggregates transparency flags, builds a
deterministic rationale string, and produces the final sorted ranking.

Normalization is NOT performed here.  Callers must pre-compute a
``NormalizedProduct`` via ``app.normalization.normalize_extraction`` and
pass it in together with the raw ``ExtractionResult``.  This ensures
normalization happens exactly once per paper.
"""

from app.core.config import settings
from app.models.extraction import ExtractionResult
from app.models.normalized import NormalizedProduct
from app.models.paper import Paper
from app.models.ranking import RankedPaperResponse
from app.models.search import SUBMISSION_PRESETS, RankingWeights, SearchRequest
from app.ranking.evidence_quality import score_evidence_quality
from app.ranking.metric_favorability import score_metric_favorability
from app.ranking.product_display import format_product_table_label
from app.ranking.product_similarity import score_product_similarity
from app.ranking.relevance import score_relevance
from app.ranking.relevance_agent import llm_relevance_raw, merge_relevance_llm

_DEFAULT_WEIGHTS = RankingWeights()

_DIMENSION_KEYS = ("R", "P", "M", "E")


def _renormalise(
    weights: dict[str, float],
    active: set[str],
) -> dict[str, float]:
    """Zero out excluded dimensions and renormalise active ones."""
    active_sum = sum(weights[k] for k in active)
    if active_sum == 0:
        return {k: 0.0 for k in weights}
    return {
        k: (weights[k] / active_sum if k in active else 0.0)
        for k in weights
    }


def _build_rationale(
    scores: dict[str, float],
    breakdowns: dict[str, dict],
    excluded: list[str],
) -> str:
    """Build a short deterministic rationale from top contributing signals."""
    parts: list[str] = []

    if "R" not in excluded:
        r = scores.get("R", 0.0)
        if r >= 0.7:
            parts.append("high relevance to query terms")
        elif r >= 0.4:
            parts.append("moderate relevance to query terms")
        else:
            parts.append("low relevance to query terms")

    if "P" not in excluded:
        p_breakdown = breakdowns.get("P", {})
        p_signals = p_breakdown.get("signals", {})
        top_matches = [k for k, v in p_signals.items() if v >= 0.8]
        p = scores.get("P", 0.0)
        if top_matches:
            parts.append(f"strong product match on {', '.join(top_matches)}")
        elif p >= 0.4:
            parts.append("partial product match")
        else:
            parts.append("weak product match")

    if "M" not in excluded:
        m_breakdown = breakdowns.get("M", {})
        matched = m_breakdown.get("matched", {})
        if matched:
            top = max(matched, key=matched.get)  # type: ignore[arg-type]
            parts.append(f"{top} scored {matched[top]:.2f} favorability")
        elif m_breakdown.get("metric_score_incomplete"):
            parts.append("no target metrics matched")

    if "E" not in excluded:
        e_breakdown = breakdowns.get("E", {})
        st = e_breakdown.get("study_type", "unknown")
        n = e_breakdown.get("sample_size")
        label = st.replace("_", " ")
        if n is not None:
            parts.append(f"{label} with n={n}")
        else:
            parts.append(label)

    return "; ".join(parts) + "." if parts else ""


async def score_composite(
    paper: Paper,
    extracted: ExtractionResult,
    normalized: NormalizedProduct,
    request: SearchRequest,
    *,
    r_precomputed: tuple[float, dict] | None = None,
) -> tuple[float, dict]:
    """Compute the composite score C ∈ [0, 1] for a single paper.

    ``normalized`` must be pre-computed by the caller via
    ``app.normalization.normalize_extraction``; it is not recomputed here.

    If ``r_precomputed`` is set (e.g. after parallel extract + LLM relevance),
    it is used as the R dimension; otherwise R is computed via LLM + recency blend
    with deterministic fallback.

    Returns ``(score, details)`` where details contains per-dimension
    scores, breakdowns, flags, weights used, and rationale.
    """
    w = request.weights or _DEFAULT_WEIGHTS
    raw_weights: dict[str, float] = {
        "R": w.R, "P": w.P, "M": w.M, "E": w.E,
    }

    scores: dict[str, float] = {}
    breakdowns: dict[str, dict] = {}
    active: set[str] = set()
    excluded: list[str] = []

    # --- R: Relevance (LLM + recency blend, or precomputed) ---
    if r_precomputed is not None:
        r_score, r_bd = r_precomputed
    elif settings.APP_MODE == "demo":
        # Demo fixtures: deterministic only (no external LLM in tests / offline).
        r_score, r_bd = score_relevance(paper, extracted, request)
    else:
        llm_raw = await llm_relevance_raw(paper, request)
        r_score, r_bd = merge_relevance_llm(llm_raw, paper, extracted, request)
    scores["R"] = r_score
    breakdowns["R"] = r_bd
    active.add("R")

    # --- P: Product Similarity (uses precomputed NormalizedProduct) ---
    sub_kw: dict = {}
    if request.submission_type:
        preset = SUBMISSION_PRESETS[request.submission_type.value]
        sub_kw["device_sub_weights"] = preset["device_sub_weights"]
        sub_kw["drug_sub_weights"] = preset["drug_sub_weights"]

    if request.target_product is not None:
        p_score, p_bd = score_product_similarity(
            normalized, request.target_product, **sub_kw
        )
        scores["P"] = p_score
        breakdowns["P"] = p_bd
        active.add("P")
    else:
        scores["P"] = 0.0
        breakdowns["P"] = {"note": "no target product profile supplied"}
        excluded.append("P")

    # --- M: Metric Favorability ---
    m_score, m_bd = score_metric_favorability(
        extracted.metrics,
        request.target_metrics,
        metrics_of_interest=request.metrics_of_interest or None,
    )
    if m_bd.get("excluded"):
        scores["M"] = 0.0
        excluded.append("M")
    else:
        scores["M"] = m_score
        active.add("M")
    breakdowns["M"] = m_bd

    # --- E: Evidence Quality ---
    e_score, e_bd = score_evidence_quality(extracted.study)
    scores["E"] = e_score
    breakdowns["E"] = e_bd
    active.add("E")

    # --- Renormalise and compute composite ---
    weights_used = _renormalise(raw_weights, active)
    composite = sum(scores[k] * weights_used[k] for k in _DIMENSION_KEYS)
    composite = max(0.0, min(1.0, composite))

    rationale = _build_rationale(scores, breakdowns, excluded)

    return composite, {
        "scores": scores,
        "breakdowns": breakdowns,
        "weights_used": weights_used,
        "dimensions_excluded": excluded,
        "metric_score_estimated": m_bd.get("metric_score_estimated", False),
        "metric_score_incomplete": m_bd.get("metric_score_incomplete", False),
        "evidence_score_estimated": e_bd.get("evidence_score_estimated", False),
        "ranking_rationale": rationale,
        "submission_type": (
            request.submission_type.value if request.submission_type else None
        ),
    }


def _evidence_label(extracted: ExtractionResult) -> str:
    """Short evidence descriptor: study type + optional sample size."""
    label = extracted.study.study_type.value.replace("_", " ")
    n = extracted.study.sample_size.value if extracted.study.sample_size is not None else None
    return f"{label}, n={n}" if n else label


async def rank_papers(
    papers: list[tuple[Paper, ExtractionResult, NormalizedProduct]],
    request: SearchRequest,
    *,
    relevance_cache: dict[str, tuple[float, dict]] | None = None,
) -> list[RankedPaperResponse]:
    """Score and rank a list of papers, returning sorted responses.

    Each input tuple is ``(paper, extracted, normalized)`` where ``normalized``
    has already been produced by ``app.normalization.normalize_extraction``.

    Optional ``relevance_cache`` maps PMID to precomputed (R score, R breakdown)
    to avoid duplicate LLM relevance calls when scores were already computed
    during extraction.

    Ties are broken by evidence_quality_score desc, then published_date desc
    (most recent first).
    """
    scored: list[tuple[float, float, Paper, dict, ExtractionResult, NormalizedProduct]] = []

    for paper, extracted, normalized in papers:
        r_pre = None
        if relevance_cache is not None:
            r_pre = relevance_cache.get(paper.uid)
        composite, details = await score_composite(
            paper, extracted, normalized, request, r_precomputed=r_pre,
        )
        scored.append((composite, details["scores"]["E"], paper, details, extracted, normalized))

    if request.similarity_threshold is not None:
        scored = [s for s in scored if s[0] >= request.similarity_threshold]

    scored.sort(
        key=lambda t: (
            t[0],
            t[1],
            t[2].published_date.toordinal() if t[2].published_date else 0,
        ),
        reverse=True,
    )

    results: list[RankedPaperResponse] = []
    for rank_idx, (composite, _, paper, details, extracted, normalized) in enumerate(scored, start=1):
        results.append(
            RankedPaperResponse(
                pmid=paper.pmid,
                doi=paper.doi,
                title=paper.title,
                abstract=paper.abstract,
                journal=paper.journal,
                published_date=paper.published_date,
                rank=rank_idx,
                composite_score=round(composite, 4),
                relevance_score=round(details["scores"]["R"], 4),
                product_similarity_score=round(details["scores"]["P"], 4),
                metric_favorability_score=round(details["scores"]["M"], 4),
                evidence_quality_score=round(details["scores"]["E"], 4),
                weights_used=details["weights_used"],
                dimensions_excluded=details["dimensions_excluded"],
                metric_score_estimated=details["metric_score_estimated"],
                metric_score_incomplete=details["metric_score_incomplete"],
                evidence_score_estimated=details["evidence_score_estimated"],
                ranking_rationale=details["ranking_rationale"],
                relevance_label=(
                    extracted.topical_relevance.label.value
                    if extracted.topical_relevance else None
                ),
                product_label=format_product_table_label(normalized),
                evidence_label=_evidence_label(extracted),
                extracted_metrics=[
                    m.model_dump(mode="json") for m in (extracted.metrics or [])
                ],
                submission_type=details.get("submission_type"),
                evidence_breakdown=details["breakdowns"].get("E"),
                metric_favorability_breakdown=details["breakdowns"].get("M"),
            )
        )

    return results
