"""Deterministic scoring functions for correlated-evidence retrieval.

Three public functions:
  - :func:`evidence_strength_score` -- authority-based strength (Step 2)
  - :func:`correlation_score` -- 11-feature pairwise correlation (Step 3)
  - :func:`explanation_value_score` -- claim-coverage explanation (Step 3)
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.retrieval.enums import SourceType
from app.retrieval.models import EvidenceRecord, ExtractedTargetProfile

if TYPE_CHECKING:
    from app.retrieval.graph import EvidenceGraph

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ ENDPOINT SYNONYM TABLE                                                  ║
# ╚══════════════════════════════════════════════════════════════════════════╝

ENDPOINT_SYNONYMS: dict[str, set[str]] = {
    "bcva": {"best corrected visual acuity", "bcva", "visual acuity", "va"},
    "iop": {"intraocular pressure", "iop"},
    "cst": {"central subfield thickness", "cst", "central retinal thickness", "crt"},
    "oct": {"optical coherence tomography", "oct thickness", "oct"},
    "udva": {"uncorrected distance visual acuity", "udva", "ucdva"},
    "ucnva": {"uncorrected near visual acuity", "ucnva", "near visual acuity"},
    "defocus curve": {"defocus curve", "defocus"},
    "contrast sensitivity": {"contrast sensitivity", "cs"},
    "sensitivity": {"sensitivity", "sens"},
    "specificity": {"specificity", "spec"},
    "imageability": {"imageability rate", "imageability", "gradable rate"},
    "af detection": {"atrial fibrillation detection", "af detection", "afib detection"},
    "injection frequency": {"injection frequency", "dosing interval", "dosing interval durability", "treatment interval"},
    "hba1c": {"hba1c", "glycated hemoglobin", "hemoglobin a1c"},
    "etdrs": {"etdrs", "etdrs letters"},
    "fluid resolution": {"fluid resolution", "subretinal fluid", "srf resolution", "irf resolution"},
    "retreatment": {"retreatment rate", "retreatment", "re-treatment"},
    "drss": {"drss", "diabetic retinopathy severity score"},
    "ppv": {"positive predictive value", "ppv"},
    "npv": {"negative predictive value", "npv"},
    "auc": {"area under curve", "auc", "auroc"},
}


def _expand_synonyms(term: str) -> set[str]:
    """Return a set of normalised synonyms for *term*."""
    t = term.strip().lower()
    for canonical, syns in ENDPOINT_SYNONYMS.items():
        if t == canonical or t in syns:
            return syns | {canonical}
    return {t}


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ EVIDENCE STRENGTH SCORE  (Step 2, unchanged)                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝

_BASE_SCORE: dict[str, float] = {
    SourceType.fda_ssed: 0.95,
    SourceType.fda_review: 0.95,
    SourceType.fda_label: 0.90,
    SourceType.dailymed_label: 0.90,
    SourceType.fda_510k: 0.85,
    SourceType.fda_pma: 0.85,
    SourceType.fda_denovo: 0.85,
    SourceType.clinicaltrials: 0.75,
    SourceType.pubmed_paper: 0.65,
    SourceType.accessgudid_device: 0.60,
    SourceType.maude_event: 0.50,
    SourceType.fda_recall: 0.50,
    SourceType.pmc_article: 0.65,
}

_RECENCY_BONUS = 0.05
_SAMPLE_SIZE_BONUS = 0.05
_RECENCY_YEARS = 3


def _published_within(record: EvidenceRecord, years: int) -> bool:
    payload = record.raw_payload or {}
    for key in ("publication_date", "date", "published", "study_first_posted", "received_date"):
        val = payload.get(key)
        if val and isinstance(val, str):
            try:
                year = int(val[:4])
                return (date.today().year - year) <= years
            except ValueError:
                pass
    return False


def _sample_size_adequate(record: EvidenceRecord) -> bool:
    payload = record.raw_payload or {}
    for key in ("enrollment", "sample_size", "n", "total_subjects"):
        val = payload.get(key)
        if val is not None:
            try:
                return int(val) >= 100
            except (ValueError, TypeError):
                pass
    return False


def _clinicaltrials_base(record: EvidenceRecord) -> float:
    payload = record.raw_payload or {}
    phase = str(payload.get("phase", "")).upper()
    if any(p in phase for p in ("3", "4", "PIVOTAL")):
        return 0.80
    if "2" in phase:
        return 0.70
    return 0.65


def _pubmed_base(record: EvidenceRecord) -> float:
    payload = record.raw_payload or {}
    pub_type = " ".join(str(v) for v in (payload.get("pub_type") or [])).lower()
    title = (record.title or "").lower()
    combined = pub_type + " " + title
    if "randomized" in combined or "rct" in combined:
        return 0.75
    if "prospective" in combined or "cohort" in combined:
        return 0.65
    if "review" in combined or "meta-analysis" in combined:
        return 0.50
    if "case" in combined:
        return 0.40
    return 0.60


def evidence_strength_score(record: EvidenceRecord) -> float:
    """Authority-based evidence strength for a single record (0.0-1.0)."""
    source = record.source_type
    if source == SourceType.clinicaltrials:
        base = _clinicaltrials_base(record)
    elif source in (SourceType.pubmed_paper, SourceType.pmc_article):
        base = _pubmed_base(record)
    else:
        base = _BASE_SCORE.get(source, 0.50)

    modifier = 0.0
    if _published_within(record, _RECENCY_YEARS):
        modifier += _RECENCY_BONUS
    if _sample_size_adequate(record):
        modifier += _SAMPLE_SIZE_BONUS

    return min(1.0, base + modifier)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ 11 PAIRWISE FEATURE FUNCTIONS                                          ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _token_set(s: str | None) -> set[str]:
    cleaned = _PUNCT_RE.sub(" ", _norm(s))
    return {t for t in cleaned.split() if len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


# 1. exact_id_match
def _exact_id_match(seed: EvidenceRecord, cand: EvidenceRecord) -> float:
    return 1.0 if seed.identifier == cand.identifier else 0.0


# 2. same_product_identity
def _same_product_identity(profile: ExtractedTargetProfile, cand: EvidenceRecord) -> float:
    profile_name = profile.product_name or profile.active_ingredient or ""
    pn_match = _norm(profile_name) == _norm(cand.product_name) and bool(profile_name)
    mfr_match = _norm(cand.manufacturer) != "" and _norm(cand.manufacturer) == _norm(profile_name)
    route_match = _norm(profile.route) == _norm(cand.route) and bool(profile.route)

    if pn_match and route_match:
        return 1.0
    if pn_match:
        return 0.7
    # partial token overlap (try both product_name and active_ingredient)
    pt = _token_set(profile_name)
    ai_tokens = _token_set(profile.active_ingredient) if profile.active_ingredient and profile.active_ingredient != profile_name else set()
    pt = pt | ai_tokens
    ct = _token_set(cand.product_name)
    if pt and ct and len(pt & ct) >= 1:
        return 0.3
    return 0.0


# 3. regulatory_bucket_match
def _regulatory_bucket_match(profile: ExtractedTargetProfile, cand: EvidenceRecord) -> float:
    payload = cand.raw_payload or {}
    openfda = payload.get("openfda", {})

    p_code_seed = _norm(profile.submission_mode)
    p_code_cand = _norm(str(openfda.get("product_code", [""])[0]) if isinstance(openfda.get("product_code"), list) else str(openfda.get("product_code", "")))
    device_class_cand = str(openfda.get("device_class", payload.get("device_class", "")))
    reg_number_cand = str(openfda.get("regulation_number", payload.get("regulation_number", "")))

    matches = 0
    if p_code_seed and p_code_cand and p_code_seed == p_code_cand:
        matches += 1
    if device_class_cand:
        matches += 1
    if reg_number_cand:
        matches += 1

    if matches >= 3:
        return 1.0
    if matches >= 2:
        return 0.6
    if matches >= 1:
        return 0.3
    return 0.0


# 4. intended_use_indication_match
def _intended_use_indication_match(profile: ExtractedTargetProfile, cand: EvidenceRecord) -> float:
    s_ind = {_norm(i) for i in profile.indication if i}
    c_ind = {_norm(i) for i in cand.indication if i}
    return _jaccard(s_ind, c_ind)


# 5. technology_material_match
def _technology_material_match(profile: ExtractedTargetProfile, cand: EvidenceRecord) -> float:
    seed_tokens: set[str] = set()
    for f in [profile.product_name, profile.active_ingredient, profile.product_type]:
        seed_tokens |= _token_set(f)
    for k in profile.key_metrics_or_endpoints:
        seed_tokens |= _token_set(k)

    cand_tokens: set[str] = set()
    cand_tokens |= _token_set(cand.product_name)
    cand_tokens |= _token_set(cand.title)
    payload = cand.raw_payload or {}
    for k in ("material", "technology", "design", "device_name"):
        cand_tokens |= _token_set(str(payload.get(k, "")))

    return _jaccard(seed_tokens, cand_tokens)


# 6. route_delivery_match
_ROUTE_GROUPS: dict[str, str] = {
    "intravitreal": "injectable",
    "intravenous": "injectable",
    "subcutaneous": "injectable",
    "intramuscular": "injectable",
    "oral": "oral",
    "topical": "topical",
    "ophthalmic": "topical",
    "implant": "implant",
}


def _route_delivery_match(profile: ExtractedTargetProfile, cand: EvidenceRecord) -> float:
    sr = _norm(profile.route)
    cr = _norm(cand.route)
    if not sr or not cr:
        return 0.0
    if sr == cr:
        return 1.0
    sg = _ROUTE_GROUPS.get(sr)
    cg = _ROUTE_GROUPS.get(cr)
    if sg and cg and sg == cg:
        return 0.5
    return 0.0


# 7. endpoint_overlap (with synonym expansion)
def _endpoint_overlap(profile: ExtractedTargetProfile, cand: EvidenceRecord) -> float:
    seed_eps: set[str] = set()
    for ep in profile.key_metrics_or_endpoints:
        seed_eps |= _expand_synonyms(ep)

    cand_eps: set[str] = set()
    for ep in cand.endpoints:
        cand_eps |= _expand_synonyms(ep)

    return _jaccard(seed_eps, cand_eps)


# 8. numeric_threshold_proximity
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def _extract_numbers(fields: list[str] | None, payload: dict[str, Any] | None = None) -> list[float]:
    nums: list[float] = []
    for f in (fields or []):
        for m in _NUMBER_RE.findall(f):
            try:
                nums.append(float(m))
            except ValueError:
                pass
    if payload:
        for key in ("threshold", "value", "result", "mean", "median"):
            v = payload.get(key)
            if v is not None:
                try:
                    nums.append(float(v))
                except (ValueError, TypeError):
                    pass
    return nums


def _numeric_threshold_proximity(profile: ExtractedTargetProfile, cand: EvidenceRecord) -> float:
    seed_nums = _extract_numbers(profile.key_thresholds)
    cand_nums = _extract_numbers(cand.endpoints, cand.raw_payload)
    if not seed_nums or not cand_nums:
        return 0.0
    best = 0.0
    for a in seed_nums:
        for b in cand_nums:
            denom = max(abs(a), abs(b))
            if denom == 0:
                continue
            proximity = 1.0 - abs(a - b) / denom
            best = max(best, proximity)
    return max(0.0, best)


# 9. citation_linkage
def _citation_linkage(
    seed: EvidenceRecord, cand: EvidenceRecord, graph: "EvidenceGraph | None"
) -> float:
    if graph is None:
        return 0.0
    for _node, edge in graph.get_neighbors(seed.identifier, edge_types=["cited_by"]):
        if edge.target_node == cand.identifier or edge.source_node == cand.identifier:
            return 1.0
    for _node, edge in graph.get_neighbors(cand.identifier, edge_types=["cited_by"]):
        if edge.target_node == seed.identifier or edge.source_node == seed.identifier:
            return 1.0
    return 0.0


# 10. regulatory_linkage
def _regulatory_linkage(
    seed: EvidenceRecord, cand: EvidenceRecord, graph: "EvidenceGraph | None"
) -> float:
    if graph is None:
        return 0.0
    edges = graph.get_edges_between(seed.identifier, cand.identifier)
    if any(e.edge_type in ("predicate_of", "review_for", "label_for") for e in edges):
        return 1.0
    return 0.0


# 11. safety_signal_overlap
def _safety_signal_overlap(
    seed: EvidenceRecord, cand: EvidenceRecord, graph: "EvidenceGraph | None"
) -> float:
    if graph is None:
        return 0.0
    edges = graph.get_edges_between(seed.identifier, cand.identifier)
    if any(e.edge_type == "safety_signal_for" for e in edges):
        return 1.0
    if cand.source_type in (SourceType.maude_event, SourceType.fda_recall):
        pn_seed = _norm(seed.product_name)
        pn_cand = _norm(cand.product_name)
        if pn_seed and pn_cand and pn_seed == pn_cand:
            return 0.5
    return 0.0


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ WEIGHTED AGGREGATION + OVERRIDES                                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝

FEATURE_WEIGHTS: dict[str, float] = {
    "same_product_identity": 0.18,
    "regulatory_bucket_match": 0.10,
    "intended_use_indication_match": 0.15,
    "technology_material_match": 0.08,
    "route_delivery_match": 0.07,
    "endpoint_overlap": 0.15,
    "numeric_threshold_proximity": 0.05,
    "citation_linkage": 0.08,
    "regulatory_linkage": 0.10,
    "safety_signal_overlap": 0.04,
}


def correlation_score(
    seed: EvidenceRecord,
    candidate: EvidenceRecord,
    seed_profile: ExtractedTargetProfile | None = None,
    graph: "EvidenceGraph | None" = None,
) -> tuple[float, dict[str, float]]:
    """Compute weighted pairwise correlation between *seed* and *candidate*.

    Returns ``(score, feature_dict)`` where *feature_dict* maps each feature
    name to its raw 0-1 value, for auditability.
    """
    features: dict[str, float] = {}

    # Override check 1: exact ID match
    features["exact_id_match"] = _exact_id_match(seed, candidate)
    if features["exact_id_match"] == 1.0:
        logger.debug("correlation_score: exact_id_match override -> 1.0")
        return 1.0, features

    profile = seed_profile or ExtractedTargetProfile(product_type="unknown")
    if not seed_profile:
        logger.warning(
            "correlation_score: no seed_profile provided, using empty default — "
            "all profile-based features will be 0"
        )

    features["same_product_identity"] = _same_product_identity(profile, candidate)
    features["regulatory_bucket_match"] = _regulatory_bucket_match(profile, candidate)
    features["intended_use_indication_match"] = _intended_use_indication_match(profile, candidate)
    features["technology_material_match"] = _technology_material_match(profile, candidate)
    features["route_delivery_match"] = _route_delivery_match(profile, candidate)
    features["endpoint_overlap"] = _endpoint_overlap(profile, candidate)
    features["numeric_threshold_proximity"] = _numeric_threshold_proximity(profile, candidate)
    features["citation_linkage"] = _citation_linkage(seed, candidate, graph)
    features["regulatory_linkage"] = _regulatory_linkage(seed, candidate, graph)
    features["safety_signal_overlap"] = _safety_signal_overlap(seed, candidate, graph)

    score = sum(
        features[fname] * FEATURE_WEIGHTS[fname]
        for fname in FEATURE_WEIGHTS
    )

    # Override check 2: regulatory_linkage floor
    if features["regulatory_linkage"] == 1.0:
        score = max(score, 0.75)
        logger.debug("correlation_score: regulatory_linkage floor -> max(score, 0.75)")

    score = max(0.0, min(1.0, score))
    return score, features


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║ EXPLANATION VALUE SCORE                                                 ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def explanation_value_score(
    seed_profile: ExtractedTargetProfile,
    candidate: EvidenceRecord,
    corr_score: float,
    strength_score: float,
) -> float:
    """How well *candidate* explains the *seed_profile*'s regulatory claims.

    ``explanation_value = corr * strength * (0.4 + 0.6 * claim_coverage)``
    """
    claims: list[str] = []
    claims.extend(seed_profile.key_metrics_or_endpoints)
    claims.extend(seed_profile.key_thresholds)
    claims.extend(seed_profile.indication)

    if not claims:
        return corr_score * strength_score * 0.4

    matched = 0
    cand_ep_expanded: set[str] = set()
    for ep in candidate.endpoints:
        cand_ep_expanded |= _expand_synonyms(ep)
    cand_ind = {_norm(i) for i in candidate.indication}
    cand_payload = candidate.raw_payload or {}

    for claim in claims:
        claim_lower = _norm(claim)
        claim_syns = _expand_synonyms(claim)

        # endpoint match
        if claim_syns & cand_ep_expanded:
            matched += 1
            continue

        # indication match
        if claim_lower in cand_ind:
            matched += 1
            continue

        # threshold / numeric match
        claim_nums = _extract_numbers([claim])
        if claim_nums:
            cand_nums = _extract_numbers(candidate.endpoints, cand_payload)
            if cand_nums:
                matched += 1
                continue

        # payload keyword check
        payload_text = " ".join(str(v) for v in cand_payload.values()).lower()
        if claim_lower in payload_text:
            matched += 1

    claim_coverage = matched / len(claims)
    return corr_score * strength_score * (0.4 + 0.6 * claim_coverage)
