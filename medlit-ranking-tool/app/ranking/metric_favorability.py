"""Metric Favorability scoring (ranking_spec §2.3).

Computes how favourable a paper's reported outcome metrics are relative
to the user-supplied target metrics.  Direction rules and thresholds come
entirely from the SearchRequest — the extraction output provides only
factual values.

When no structured ``target_metrics`` are supplied but the user has provided
``metrics_of_interest`` (free-text metric names), a **coverage fallback** is
used: M = (number of user metrics found in the paper) / (total user metrics).
Matching is case-insensitive and uses token overlap so "posterior capsule
opacification" matches "PCO" if either string is a substring of the other.

Qualified phrases emitted by NL parsing (e.g. "IOP ~20 mmHg postoperative")
are stripped of numeric qualifiers and units before matching so they still
map to canonical extracted names like "intraocular pressure".
"""

import re

from app.models.extraction import ExtractedMetric, MetricValueType
from app.models.search import DirectionMode, TargetMetric


# ---------------------------------------------------------------------------
# Qualifier / unit stripping — applied to user-supplied metric names before
# abbreviation expansion and token-overlap matching so that qualified phrases
# like "IOP ~20 mmHg postoperative" reduce to "IOP postoperative" and then
# expand correctly to ["IOP", "iop", "intraocular pressure", ...].
# ---------------------------------------------------------------------------

_METRIC_UNITS_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*)?(?:mm\s*hg|mmhg|%|µm|\u00b5m|logmar|letters?|db\b|ml\b|mg\b)\b",
    re.IGNORECASE,
)
_NUMERIC_QUALIFIER_RE = re.compile(r"[~<>≥≤]?\s*\d+(?:\.\d+)?")


def _strip_metric_qualifiers(s: str) -> str:
    """Remove numeric values and clinical units from a metric label.

    Turns "IOP ~20 mmHg postoperative" → "IOP postoperative" so that
    abbreviation expansion in _metric_query_variants can still fire.
    """
    s = _METRIC_UNITS_RE.sub(" ", s)
    s = _NUMERIC_QUALIFIER_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _numeric_value_for(metric: ExtractedMetric) -> float | None:
    """Return the primary numeric value usable for favorability scoring.

    Range-typed metrics use the midpoint.  Binary and text metrics are
    not scoreable numerically.
    """
    match metric.value_type:
        case MetricValueType.NUMERIC | MetricValueType.PERCENTAGE:
            return metric.numeric_value
        case MetricValueType.RANGE:
            if metric.value_min is not None and metric.value_max is not None:
                return (metric.value_min + metric.value_max) / 2.0
    return None


def _compute_favorability(value: float, target: TargetMetric) -> float:
    nr = target.normalisation_range
    match target.direction:
        case DirectionMode.HIGHER_BETTER:
            assert target.threshold is not None
            return _clip((value - target.threshold) / nr)
        case DirectionMode.LOWER_BETTER:
            assert target.threshold is not None
            return _clip((target.threshold - value) / nr)
        case DirectionMode.RANGE_BEST:
            assert target.range_lo is not None and target.range_hi is not None
            if target.range_lo <= value <= target.range_hi:
                return 1.0
            dist = min(abs(value - target.range_lo), abs(value - target.range_hi))
            return _clip(1.0 - dist / nr)
        case DirectionMode.CLOSER_BETTER:
            assert target.target is not None
            return _clip(1.0 - abs(value - target.target) / nr)


def _metric_name_matches_core(a: str, b: str) -> bool:
    """Inner match after both sides are lowered/stripped."""
    if a == b:
        return True
    if a in b or b in a:
        return True
    # Underscores in normalized names (e.g. best_corrected_visual_acuity)
    norm = lambda s: s.replace("-", " ").replace("_", " ")
    tokens_a = {t for t in norm(a).split() if len(t) >= 3}
    tokens_b = {t for t in norm(b).split() if len(t) >= 3}
    return bool(tokens_a & tokens_b)


def _metric_query_variants(user_name: str) -> list[str]:
    """Expand user-supplied metric hints with common ophthalmology synonyms.

    Accepts both bare abbreviations ("IOP") and qualified phrases
    ("IOP ~20 mmHg postoperative") — the qualifier-stripped version is
    used for abbreviation detection so both forms expand correctly.
    """
    raw = user_name.strip()
    if not raw:
        return []
    low = raw.lower().replace("‑", "-")
    # Also check qualifier-stripped version for abbreviation matching
    low_stripped = _strip_metric_qualifiers(low)
    out: list[str] = [raw]

    def _has(abbr: str) -> bool:
        """True when the abbreviation appears as a whole word in low or low_stripped."""
        pat = re.compile(r"\b" + re.escape(abbr) + r"\b", re.IGNORECASE)
        return bool(pat.search(low) or pat.search(low_stripped))

    # Abbreviations ↔ phrases (PMID 39350227 uses CST, BCVA, MV in abstract)
    if _has("bcva") or "best-corrected visual acuity" in low or "best corrected visual acuity" in low:
        out.extend(["BCVA", "bcva", "visual acuity", "best corrected visual acuity"])
    if _has("cst") or "central subfield thickness" in low:
        out.extend(["CST", "cst", "central subfield thickness", "subfield thickness"])
    if _has("mv") or "macular volume" in low:
        out.extend(["MV", "mv", "macular volume"])
    # Central foveal / macular thickness (DME papers often use CFT or CMT)
    if _has("cft") or "central foveal thickness" in low or "foveal thickness" in low:
        out.extend(
            ["CFT", "cft", "central foveal thickness", "foveal thickness", "central macular thickness"]
        )
    if _has("cmt") or "central macular thickness" in low:
        out.extend(
            ["CMT", "cmt", "central macular thickness", "central retinal thickness", "macular thickness"]
        )
    # IOP (3-letter abbreviation does not token-match intraocular_pressure)
    if _has("iop") or "intraocular pressure" in low:
        out.extend(["IOP", "iop", "intraocular pressure", "intraocular_pressure"])
    # Visual acuity at distance / intermediate / near (IOL outcomes)
    if _has("udva") or "uncorrected distance visual acuity" in low:
        out.extend(
            ["UDVA", "udva", "uncorrected distance visual acuity", "uncorrected distance va"]
        )
    if _has("cdva") or "corrected distance visual acuity" in low:
        out.extend(
            ["CDVA", "cdva", "corrected distance visual acuity", "corrected distance va"]
        )
    if _has("uiva") or "uncorrected intermediate visual acuity" in low:
        out.extend(
            ["UIVA", "uiva", "uncorrected intermediate visual acuity", "intermediate visual acuity"]
        )
    if _has("unva") or "uncorrected near visual acuity" in low:
        out.extend(
            ["UNVA", "unva", "uncorrected near visual acuity", "uncorrected near va", "near visual acuity"]
        )
    # Posterior capsule opacification (PCO is too short for token overlap alone)
    if _has("pco") or "posterior capsule opacification" in low:
        out.extend(["PCO", "pco", "posterior capsule opacification", "capsule opacification"])
    # RNFL (glaucoma)
    if _has("rnfl") or "retinal nerve fiber" in low or "retinal nerve fibre" in low:
        out.extend(
            ["RNFL", "rnfl", "retinal nerve fiber layer", "retinal nerve fibre layer", "nerve fiber layer"]
        )
    # Contrast sensitivity (IOL functional outcomes)
    if _has("cs") or "contrast sensitivity" in low:
        out.extend(["contrast sensitivity", "CS", "Pelli-Robson"])
    # Spectacle independence (refractive / IOL)
    if "spectacle" in low and "independence" in low:
        out.extend(["spectacle independence", "spectacle free", "glasses independence"])
    # Glaucoma medication burden (Ahmed / XEN trials)
    if _has("medications") or "medication count" in low or "glaucoma medications" in low:
        out.extend(
            ["medications", "medication count", "glaucoma medications", "antiglaucoma medications"]
        )
    # Dedupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        k = x.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq


def _metric_name_matches(user_name: str, extracted_name: str) -> bool:
    """Case-insensitive soft match between a user-supplied metric name and an
    extracted canonical name.

    Returns True when either name is a substring of the other, or when their
    lowercase token sets share at least one common word of length ≥ 3.
    This lets "BCVA" match "best corrected visual acuity" and "PCO" match
    "posterior capsule opacification".
    """
    for variant in _metric_query_variants(user_name):
        a = variant.lower().strip()
        b = extracted_name.lower().strip()
        if _metric_name_matches_core(a, b):
            return True
    return False


def _score_coverage_fallback(
    extracted_metrics: list[ExtractedMetric],
    metrics_of_interest: list[str],
) -> tuple[float, dict]:
    """Metric coverage fallback used when no structured TargetMetric objects
    are provided.

    Score = (number of user metrics found in paper) / (total user metrics).
    Each user metric is considered "found" if any extracted metric name
    matches via ``_metric_name_matches``.

    Qualified phrases like "IOP ~20 mmHg postoperative" are stripped of
    numeric qualifiers and units before matching so they expand correctly to
    canonical synonyms (e.g. "intraocular pressure").
    """
    found: list[str] = []
    not_found: list[str] = []

    extracted_names = [
        m.metric_name_normalized or m.metric_name_raw or ""
        for m in extracted_metrics
    ]

    for user_m in metrics_of_interest:
        # Try original form first; fall back to qualifier-stripped form
        canonical = _strip_metric_qualifiers(user_m)
        if any(
            _metric_name_matches(user_m, ext) or _metric_name_matches(canonical, ext)
            for ext in extracted_names
        ):
            found.append(user_m)
        else:
            not_found.append(user_m)

    coverage = len(found) / len(metrics_of_interest)
    score = _clip(coverage)

    return score, {
        "matched": {m: 1.0 for m in found},
        "unmatched": not_found,
        "coverage_mode": True,
        "coverage_ratio": f"{len(found)}/{len(metrics_of_interest)}",
        "metric_score_estimated": True,
        "metric_score_incomplete": len(found) == 0,
    }


def score_metric_favorability(
    extracted_metrics: list[ExtractedMetric],
    target_metrics: list[TargetMetric],
    metrics_of_interest: list[str] | None = None,
) -> tuple[float, dict]:
    """Compute the metric favorability score M ∈ [0, 1].

    Returns ``(score, breakdown)`` where breakdown includes per-metric
    results, the ``metric_score_estimated`` flag, and the
    ``metric_score_incomplete`` flag.

    When ``target_metrics`` is empty but ``metrics_of_interest`` is supplied,
    falls back to coverage scoring: M = fraction of the user's named metrics
    that appear anywhere in the extracted metrics for this paper.
    """
    if not target_metrics:
        if metrics_of_interest:
            return _score_coverage_fallback(extracted_metrics, metrics_of_interest)
        return 0.0, {
            "matched": {},
            "metric_score_estimated": False,
            "metric_score_incomplete": False,
            "note": "no target metrics supplied — dimension excluded",
            "excluded": True,
        }

    extracted_by_name: dict[str, ExtractedMetric] = {
        m.metric_name_normalized: m for m in extracted_metrics
        if m.metric_name_normalized
    }

    matched: dict[str, float] = {}
    unmatched: list[str] = []

    for tm in target_metrics:
        ext = extracted_by_name.get(tm.metric_name_normalized)
        if ext is None:
            unmatched.append(tm.metric_name_normalized)
            continue
        value = _numeric_value_for(ext)
        if value is None:
            unmatched.append(tm.metric_name_normalized)
            continue
        matched[tm.metric_name_normalized] = _compute_favorability(value, tm)

    metric_score_incomplete = len(matched) == 0
    metric_score_estimated = (
        not metric_score_incomplete and len(matched) < len(target_metrics)
    )

    if metric_score_incomplete:
        score = 0.0
    else:
        score = sum(matched.values()) / len(matched)
        score = _clip(score)

    return score, {
        "matched": matched,
        "unmatched": unmatched,
        "metric_score_estimated": metric_score_estimated,
        "metric_score_incomplete": metric_score_incomplete,
    }
