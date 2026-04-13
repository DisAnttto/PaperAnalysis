"""Evidence Quality scoring (ranking_spec §2.4).

Maps study design, sample size, follow-up duration, and comparator quality
to a quality tier via deterministic lookup tables and modifiers.  An
optional evidence-domain cap penalises non-human evidence.  The LLM emits
only controlled-vocabulary labels; this module converts them to a numeric
score aligned with FDA/CDRH-style ophthalmology evidence hierarchy.
"""

from app.models.extraction import (
    ComparatorType,
    EvidenceDomain,
    StudyExtraction,
    StudyType,
)

STUDY_DESIGN_SCORES: dict[str, float] = {
    StudyType.SYSTEMATIC_REVIEW: 1.00,
    StudyType.META_ANALYSIS: 1.00,
    StudyType.RCT: 0.90,
    StudyType.PROSPECTIVE_COHORT: 0.70,
    StudyType.RETROSPECTIVE_COHORT: 0.50,
    StudyType.CASE_CONTROL: 0.40,
    StudyType.CASE_SERIES: 0.30,
    StudyType.CASE_REPORT: 0.15,
    StudyType.BENCH_STUDY: 0.15,
    StudyType.IN_VITRO_STUDY: 0.15,
    StudyType.ANIMAL_STUDY: 0.20,
    StudyType.NARRATIVE_REVIEW: 0.15,
    StudyType.UNKNOWN: 0.20,
}

DOMAIN_CAPS: dict[str, float | None] = {
    EvidenceDomain.HUMAN_CLINICAL: None,
    EvidenceDomain.ANIMAL: 0.60,
    EvidenceDomain.IN_VITRO: 0.40,
    EvidenceDomain.BENCH: 0.40,
    EvidenceDomain.MIXED: 0.50,
    EvidenceDomain.UNKNOWN: None,
}


def _sample_size_modifier(n: int | None) -> float:
    """Ophthalmology-oriented tiers (pivotal-scale ~300–500 eyes)."""
    if n is None:
        return 0.0
    if n >= 500:
        return 0.10
    if n >= 300:
        return 0.08
    if n >= 100:
        return 0.05
    if n >= 30:
        return 0.02
    if n >= 10:
        return 0.00
    return -0.05


def _follow_up_modifier(months: int | None) -> float:
    if months is None:
        return 0.0
    if months >= 24:
        return 0.08
    if months >= 12:
        return 0.05
    if months >= 6:
        return 0.02
    return 0.0


def _comparator_modifier(comparator: ComparatorType | None) -> float:
    if comparator is None:
        return 0.0
    match comparator:
        case ComparatorType.ACTIVE:
            return 0.05
        case ComparatorType.SHAM | ComparatorType.PLACEBO:
            return 0.03
        case ComparatorType.HISTORICAL:
            return 0.01
        case ComparatorType.NONE | ComparatorType.UNKNOWN:
            return 0.0


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_evidence_quality(
    study: StudyExtraction,
) -> tuple[float, dict]:
    """Compute the evidence quality score E ∈ [0, 1].

    ``E = clip(base + sample_modifier + follow_up_modifier +
    comparator_modifier)`` then apply domain cap.

    Returns ``(score, breakdown)`` with base score, modifiers, cap applied,
    and the ``evidence_score_estimated`` flag.
    """
    study_label = study.study_type.value
    base = STUDY_DESIGN_SCORES.get(
        study_label, STUDY_DESIGN_SCORES[StudyType.UNKNOWN],
    )

    sample_n = study.sample_size.value if study.sample_size is not None else None
    size_mod = _sample_size_modifier(sample_n)

    follow_m = (
        study.follow_up_months.value
        if study.follow_up_months is not None
        else None
    )
    follow_mod = _follow_up_modifier(follow_m)

    comp_mod = _comparator_modifier(study.comparator_type)

    score = _clip(base + size_mod + follow_mod + comp_mod)

    domain_label = study.evidence_domain.value
    cap = DOMAIN_CAPS.get(domain_label)
    cap_applied = False
    if cap is not None and score > cap:
        score = cap
        cap_applied = True

    evidence_score_estimated = (
        study_label == StudyType.UNKNOWN and sample_n is None
    )

    return score, {
        "study_type": study_label,
        "base_score": base,
        "sample_size": sample_n,
        "size_modifier": size_mod,
        "follow_up_months": follow_m,
        "follow_up_modifier": follow_mod,
        "comparator_type": (
            study.comparator_type.value
            if study.comparator_type is not None
            else None
        ),
        "comparator_modifier": comp_mod,
        "evidence_domain": domain_label,
        "domain_cap": cap,
        "cap_applied": cap_applied,
        "evidence_score_estimated": evidence_score_estimated,
    }
