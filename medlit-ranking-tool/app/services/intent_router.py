"""Rule-based intent classification and source routing.

Given a query string and an optional TargetProductProfile, the router:
  1. Classifies the query **intent** (efficacy, safety, regulatory, guidelines, landscape).
  2. Selects which **sources** should be queried, with per-source budget caps.

This is additive — when the router returns ``None`` for enabled_sources, the
pool falls back to the existing behaviour (query all 6 sources).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from app.models.search import SearchRequest, TargetProductProfile


class QueryIntent(str, Enum):
    EFFICACY = "efficacy"
    SAFETY = "safety"
    REGULATORY = "regulatory"
    GUIDELINES = "guidelines"
    LANDSCAPE = "landscape"
    GENERAL = "general"


ALL_SOURCES = frozenset({
    "PubMed",
    "OpenAlex",
    "openFDA_device",
    "openFDA_drug",
    "ClinicalTrials",
    "DailyMed",
    "AccessGUDID",
})

_LITERATURE_SOURCES = frozenset({"PubMed", "OpenAlex", "ClinicalTrials"})
_REGULATORY_SOURCES = frozenset({
    "openFDA_device", "openFDA_drug", "DailyMed", "AccessGUDID",
})

_EFFICACY_PATTERNS = re.compile(
    r"\b(efficacy|effective|outcome|endpoint|bcva|iop|visual\s*acuity|"
    r"response\s*rate|survival|remission|improvement)\b",
    re.IGNORECASE,
)
_SAFETY_PATTERNS = re.compile(
    r"\b(safety|adverse|side\s*effect|complication|toxicity|"
    r"contraindication|mortality|morbidity|harm|recall|maude|"
    r"risk\s*factor|elevation|spike|transient|threshold|"
    r"hypertension|high[\s-]risk|intervention|trigger)\b",
    re.IGNORECASE,
)
_REGULATORY_PATTERNS = re.compile(
    r"\b(510\s*\(?k\)?|pma|de\s*novo|fda|clearance|approval|"
    r"premarket|predicate|k\d{6}|den\d{6}|bla|nda|anda|"
    r"regulatory|submission|labeling|label)\b",
    re.IGNORECASE,
)
_GUIDELINE_PATTERNS = re.compile(
    r"\b(guideline|consensus|recommendation|standard\s*of\s*care|"
    r"clinical\s*practice|aao|asrs|who|nice|aha|acc)\b",
    re.IGNORECASE,
)


@dataclass
class RoutingDecision:
    """Output of the intent router."""

    intent: QueryIntent
    enabled_sources: frozenset[str] = field(default_factory=lambda: ALL_SOURCES)
    budget_overrides: dict[str, int] = field(default_factory=dict)
    reasoning: str = ""


def classify_intent(
    query: str,
    target_product: TargetProductProfile | None = None,
    submission_type: str | None = None,
) -> QueryIntent:
    """Classify the query into an intent category using keyword patterns."""
    scores: dict[QueryIntent, int] = {i: 0 for i in QueryIntent}

    if _EFFICACY_PATTERNS.search(query):
        scores[QueryIntent.EFFICACY] += 2
    if _SAFETY_PATTERNS.search(query):
        scores[QueryIntent.SAFETY] += 2
    if _REGULATORY_PATTERNS.search(query):
        scores[QueryIntent.REGULATORY] += 2
    if _GUIDELINE_PATTERNS.search(query):
        scores[QueryIntent.GUIDELINES] += 2

    if submission_type:
        st = submission_type.lower()
        if st in ("510k", "pma", "de_novo"):
            scores[QueryIntent.REGULATORY] += 1
        if st in ("pma", "bla"):
            scores[QueryIntent.EFFICACY] += 1

    if target_product:
        if target_product.device_category:
            scores[QueryIntent.REGULATORY] += 1
        if target_product.active_ingredient:
            scores[QueryIntent.EFFICACY] += 1

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return QueryIntent.GENERAL

    # Tie-break: prefer SAFETY over EFFICACY when both share the top score.
    # When both safety and efficacy signals are present, the safety-aware
    # routing is more conservative and more inclusive for clinical evidence.
    if (
        scores[QueryIntent.SAFETY] > 0
        and scores[QueryIntent.SAFETY] == scores[QueryIntent.EFFICACY]
        and scores[QueryIntent.SAFETY] == scores[best]
    ):
        best = QueryIntent.SAFETY

    return best


def route_sources(
    intent: QueryIntent,
    pool_size: int,
    target_type: str | None = None,
) -> RoutingDecision:
    """Select sources and budget based on intent.

    ``target_type`` ("device" | "drug" | None) is used to suppress sources that
    are structurally irrelevant — e.g. drug-label openFDA search is noise when
    the target is explicitly a device.
    """
    is_device = (target_type or "").lower() == "device"

    if intent == QueryIntent.EFFICACY:
        sources: set[str] = {"PubMed", "OpenAlex", "ClinicalTrials", "openFDA_drug", "DailyMed"}
        if is_device:
            sources.discard("openFDA_drug")
        return RoutingDecision(
            intent=intent,
            enabled_sources=frozenset(sources),
            reasoning="Efficacy queries prioritise literature and clinical trials.",
        )

    if intent == QueryIntent.SAFETY:
        sources = set(ALL_SOURCES)
        if is_device:
            sources.discard("openFDA_drug")
        return RoutingDecision(
            intent=intent,
            enabled_sources=frozenset(sources),
            budget_overrides={"openFDA_device": pool_size},
            reasoning="Safety queries search all sources with full budget for regulatory.",
        )

    if intent == QueryIntent.REGULATORY:
        sources = set(ALL_SOURCES)
        if is_device:
            sources.discard("openFDA_drug")
        return RoutingDecision(
            intent=intent,
            enabled_sources=frozenset(sources),
            budget_overrides={
                "openFDA_device": pool_size,
                "AccessGUDID": pool_size,
            },
            reasoning="Regulatory queries emphasise FDA databases.",
        )

    if intent == QueryIntent.GUIDELINES:
        return RoutingDecision(
            intent=intent,
            enabled_sources=frozenset({"PubMed", "OpenAlex", "ClinicalTrials", "DailyMed"}),
            reasoning="Guideline queries focus on literature and clinical registries.",
        )

    # LANDSCAPE or GENERAL: query everything, still filter drug labels for devices
    sources = set(ALL_SOURCES)
    if is_device:
        sources.discard("openFDA_drug")
    return RoutingDecision(
        intent=intent,
        enabled_sources=frozenset(sources),
        reasoning="General/landscape queries search all sources.",
    )


def get_routing(request: SearchRequest) -> RoutingDecision:
    """Convenience: classify intent and route in one call."""
    intent = classify_intent(
        request.query,
        request.target_product,
        request.submission_type,
    )
    target_type = (
        request.target_product.target_type if request.target_product else None
    )
    return route_sources(intent, request.pool_size, target_type=target_type)
