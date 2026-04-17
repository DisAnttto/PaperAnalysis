"""Hybrid score-and-rank triage: deterministic pre-scoring + LLM scoring.

Two independent tracks evaluate papers on their own terms:

  Literature track  – PubMed papers.  Uses query-recall + profile-signal +
                      MeSH-overlap pre-score and a clinical-evidence LLM prompt.
  Regulatory track  – openFDA / ClinicalTrials / DailyMed / AccessGUDID records.
                      Uses a renormalised pre-score that does not penalise absent
                      abstracts/MeSH, and a product-identity-focused LLM prompt.

Each track runs an identical 3-phase pipeline:
  Phase 1 – Deterministic pre-score (keyword recall + target profile signals)
  Phase 2 – LLM relevance scoring (score 0-10, not binary select)
  Phase 3 – Combined scoring with anchor guarantees → top-N selection

Slots are split 70 % literature / 30 % regulatory when both source types are
present.  Surplus slots from an under-populated track spill over to the other.

Anchor papers (title contains the target drug/device name) are guaranteed
to survive triage in the literature track regardless of LLM score.
"""

from __future__ import annotations

import math
import re
import string
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from loguru import logger
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_llm_client_config, get_llm_extra_request_kwargs
from app.models.paper import Paper
from app.models.search import TargetProductProfile
from app.ranking.metric_favorability import _metric_query_variants, _strip_metric_qualifiers

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ABSTRACT_MAX_LEN = 1500

# Literature (PubMed) pre-score weights
# metric_signal is non-zero only when metrics_of_interest is supplied; the
# weights are renormalised at runtime so the sum stays 1.0 regardless.
_PRE_WEIGHTS = {
    "query_title":    0.22,
    "query_abstract": 0.18,
    "profile_signal": 0.30,
    "mesh_overlap":   0.10,
    "metric_signal":  0.20,
}

# Regulatory pre-score weights — renormalised to omit abstract / MeSH,
# replaced with an identifier-match signal unique to regulatory records.
_REGULATORY_PRE_WEIGHTS = {
    "query_title": 0.35,
    "profile_signal": 0.55,
    "identifier_match": 0.10,
}

_PRE_SCORE_W = 0.35
_LLM_SCORE_W = 0.65
_ANCHOR_FLOOR = 0.5
_LLM_SHORTLIST_FACTOR = 3

_PUBMED_SOURCE = "PubMed"

# Sources that belong to the regulatory track
_REGULATORY_SOURCES = frozenset({"openFDA", "ClinicalTrials", "DailyMed", "AccessGUDID"})

# Fraction of max_results reserved for regulatory records when both tracks
# are populated.  The remainder goes to the literature track.
_REGULATORY_SLOT_FRACTION = 0.30

# ---------------------------------------------------------------------------
# Glaucoma-procedure pre-score penalty
# Applied when the search targets a non-glaucoma device (e.g. IOL) and the
# query does not mention glaucoma.  Papers whose titles contain these terms
# are primarily about combined glaucoma procedures rather than routine phaco
# or IOL safety, so they receive a downward pre-score nudge.
# They are NOT hard-excluded — high relevance can still overcome the penalty.
# ---------------------------------------------------------------------------

_GLAUCOMA_PROCEDURE_TERMS = frozenset({
    "trabeculectomy",
    "trabeculotomy",
    "goniotomy",
    "goniosynechialysis",
    "canaloplasty",
    "viscocanalostomy",
    "gatt",
    "trabectome",
})

# Device categories that legitimately involve glaucoma procedures — skip penalty.
_GLAUCOMA_DEVICE_CATEGORIES = frozenset({
    "glaucoma_drainage_device",
    "glaucoma_stent",
    "migs_device",
    "trabecular_bypass_stent",
    "ab_interno_trabeculotomy",
})

_GLAUCOMA_PROCEDURE_PENALTY = 0.15


# ---------------------------------------------------------------------------
# Fast metric signal scanner (O(n) regex, no LLM)
# Used both for pre-scoring and for the shortlist metric-hit quota.
# ---------------------------------------------------------------------------

_METRIC_UNIT_RE = re.compile(
    r"\d{1,4}(?:\.\d+)?\s*(?:mm\s*hg|mmhg|%|µm|\u00b5m|logmar|letters?|db\b|ml\b|mg\b)",
    re.IGNORECASE,
)


def _metric_signal(
    paper: Paper,
    metrics_of_interest: list[str] | None,
    *,
    _cache: dict | None = None,
) -> float:
    """Quick regex scan: does this paper discuss any user-specified metric?

    Returns a score in [0, 1]:
      0.0  — metrics_of_interest is empty/None, or no match found
      >0   — at least one metric name variant appears in title/abstract
      1.0  — metric name + numeric unit both present and co-located

    Pass a dict as *_cache* to avoid recomputing for the same paper uid.
    """
    if not metrics_of_interest:
        return 0.0

    uid = paper.uid or id(paper)
    if _cache is not None and uid in _cache:
        return _cache[uid]

    text = " ".join(filter(None, [paper.title or "", paper.abstract or ""])).lower()
    if not text.strip():
        if _cache is not None:
            _cache[uid] = 0.0
        return 0.0

    # Collect all variant strings for every user metric
    all_variants: list[str] = []
    for user_m in metrics_of_interest:
        stripped = _strip_metric_qualifiers(user_m)
        for v in _metric_query_variants(user_m) + (_metric_query_variants(stripped) if stripped != user_m else []):
            vl = v.lower()
            if vl not in all_variants:
                all_variants.append(vl)

    name_hit = any(v in text for v in all_variants)
    unit_hit = bool(_METRIC_UNIT_RE.search(paper.abstract or ""))

    if not name_hit:
        score = 0.0
    elif name_hit and unit_hit:
        # Bonus if name and unit are within 80 chars of each other
        co_located = False
        for v in all_variants:
            idx = text.find(v)
            if idx == -1:
                continue
            snippet = text[max(0, idx - 80): idx + 80 + len(v)]
            if _METRIC_UNIT_RE.search(snippet):
                co_located = True
                break
        score = 1.0 if co_located else 0.8
    else:
        score = 0.5

    if _cache is not None:
        _cache[uid] = score
    return score


# ---------------------------------------------------------------------------
# Helpers shared across phases
# ---------------------------------------------------------------------------


def _get_client() -> AsyncOpenAI:
    c = get_llm_client_config()
    return AsyncOpenAI(
        api_key=c.api_key,
        base_url=c.base_url,
        timeout=120.0,
    )


def _tokenize(text: str) -> set[str]:
    """Whitespace tokens, lowercased, punctuation stripped (matches PubMed text)."""
    out: set[str] = set()
    for w in text.lower().split():
        t = w.strip(string.punctuation)
        if len(t) > 2:
            out.add(t)
    return out


def _recall(query_tokens: set[str], text_tokens: set[str]) -> float:
    if not query_tokens or not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens)


def _contains_ci(haystack: str, needle: str) -> bool:
    """Case-insensitive substring check (both stripped)."""
    return needle.strip().lower() in haystack.lower()


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


# ---------------------------------------------------------------------------
# Phase 1: Deterministic pre-scoring — shared helpers
# ---------------------------------------------------------------------------

def _profile_terms(tp: TargetProductProfile | None) -> list[str]:
    """Collect all searchable terms from the target profile."""
    if tp is None:
        return []
    terms: list[str] = []
    if tp.active_ingredient:
        terms.append(tp.active_ingredient.strip().lower())
    if tp.product_name:
        terms.append(tp.product_name.strip().lower())
    if tp.device_category:
        terms.append(tp.device_category.replace("_", " ").strip().lower())
    for ind in tp.indications:
        s = ind.strip().replace("_", " ").replace("-", " ").lower()
        if s:
            terms.append(s)
    if tp.intended_use:
        terms.append(tp.intended_use.strip().lower())
    if tp.drug_class:
        dc = tp.drug_class
        if isinstance(dc, list):
            for c in dc:
                terms.append(str(c).replace("_", " ").strip().lower())
        else:
            terms.append(str(dc).replace("_", " ").strip().lower())
    return [t for t in terms if t]


def _anchor_names(tp: TargetProductProfile | None) -> list[str]:
    """Primary name terms used for anchor detection (drug/device name)."""
    if tp is None:
        return []
    names: list[str] = []
    if tp.active_ingredient:
        names.append(tp.active_ingredient.strip().lower())
    if tp.product_name:
        pn = tp.product_name.strip().lower()
        if pn not in names:
            names.append(pn)
    return [n for n in names if n]


def _normalize_match_text(text: str) -> str:
    """Lowercase + common PubMed unicode variants for substring matching."""
    t = text.lower()
    for old, new in (
        ("naïve", "naive"),
        ("naıve", "naive"),
        ("–", "-"),
        ("—", "-"),
    ):
        t = t.replace(old, new)
    return t


def _squish(s: str) -> str:
    """Collapse hyphens/whitespace so 'age-related' matches 'age related'."""
    return " ".join(s.replace("-", " ").split())


def _term_in_haystack(term: str, hay_norm: str) -> bool:
    """True if profile term appears in normalized haystack (hyphen tolerant)."""
    tn = _squish(_normalize_match_text(term).replace("_", " "))
    if len(tn) < 2:
        return False
    hn = _squish(hay_norm)
    if tn in hn:
        return True
    return False


def _profile_signal(paper: Paper, tp: TargetProductProfile | None) -> float:
    """Score how strongly the paper matches the target product profile.

    Drug/device name in the title is necessary but not sufficient for a flat 1.0:
    many papers share the same anchor; we add a capped bonus for non-name profile
    terms (indications, intended_use, etc.) in title vs abstract so highly aligned
    papers (e.g. treatment-naïve nAMD) sort above generic same-drug titles.
    """
    if tp is None:
        return 0.0

    title = _normalize_match_text(paper.title or "")
    abstract = _normalize_match_text(paper.abstract or "")
    combined = title + " " + abstract

    names = _anchor_names(tp)
    name_in_title = any(_squish(n) in _squish(title) for n in names)
    name_in_abstract = any(_squish(n) in _squish(abstract) for n in names if abstract)

    profile_terms = _profile_terms(tp)
    non_name = [t for t in profile_terms if t not in names]

    def _indication_bonus() -> float:
        if not non_name:
            return 0.0
        b = 0.0
        for term in non_name:
            if len(term.strip()) < 2:
                continue
            in_title = _term_in_haystack(term, title)
            in_abs = _term_in_haystack(term, abstract) if abstract else False
            if in_title:
                b += 0.07
            elif in_abs:
                b += 0.035
        return min(0.36, b)

    bonus = _indication_bonus()

    if name_in_title:
        return max(0.0, min(1.0, 0.70 + bonus))
    if name_in_abstract:
        return max(0.0, min(1.0, 0.52 + bonus))

    if not non_name:
        return 0.0
    hits = sum(1 for t in non_name if _term_in_haystack(t, combined))
    return min(0.5, hits / len(non_name))


def _mesh_overlap(paper: Paper, tp: TargetProductProfile | None) -> float:
    """Fraction of profile terms found in the paper's MeSH headings."""
    if tp is None or not paper.mesh_terms:
        return 0.0
    profile = _profile_terms(tp)
    if not profile:
        return 0.0
    mesh_lower = {m.lower() for m in paper.mesh_terms}
    mesh_joined = " ".join(mesh_lower)
    hits = sum(1 for t in profile if t in mesh_joined)
    return min(1.0, hits / len(profile))


# ---------------------------------------------------------------------------
# Phase 1: Literature pre-score (PubMed track)
# ---------------------------------------------------------------------------

def prescore_paper(
    paper: Paper,
    query: str,
    target_product: TargetProductProfile | None,
    metrics_of_interest: list[str] | None = None,
    *,
    _metric_cache: dict | None = None,
) -> float:
    """Deterministic relevance pre-score in [0, 1] for literature (PubMed) papers.

    Combines query-token recall over title/abstract, target profile signal
    strength, MeSH term overlap, and (when supplied) a fast metric signal
    that rewards papers discussing user-specified clinical endpoints.
    """
    query_tokens = _tokenize(query)
    title_tokens = _tokenize(paper.title or "")
    abstract_tokens = _tokenize(paper.abstract or "")

    msig = _metric_signal(paper, metrics_of_interest, _cache=_metric_cache)

    raw_signals = {
        "query_title":    _recall(query_tokens, title_tokens),
        "query_abstract": _recall(query_tokens, abstract_tokens),
        "profile_signal": _profile_signal(paper, target_product),
        "mesh_overlap":   _mesh_overlap(paper, target_product),
        "metric_signal":  msig,
    }

    # When metrics_of_interest is absent, metric_signal is 0 for every paper,
    # which would silently steal 20 % of the score.  Renormalise weights to
    # exclude the metric_signal dimension in that case.
    if not metrics_of_interest:
        active_keys = [k for k in raw_signals if k != "metric_signal"]
        total_w = sum(_PRE_WEIGHTS[k] for k in active_keys)
        signals = {k: raw_signals[k] * (_PRE_WEIGHTS[k] / total_w) for k in active_keys}
    else:
        signals = {k: raw_signals[k] * _PRE_WEIGHTS[k] for k in raw_signals}

    score = sum(signals.values())
    score = max(0.0, min(1.0, score))

    # Penalise papers primarily about combined glaucoma procedures when the
    # target is not a glaucoma device and the query did not ask about glaucoma.
    if target_product and "glaucoma" not in query.lower():
        cat = (target_product.device_category or "").lower()
        if cat and cat not in _GLAUCOMA_DEVICE_CATEGORIES:
            title_lower = (paper.title or "").lower()
            if any(term in title_lower for term in _GLAUCOMA_PROCEDURE_TERMS):
                score = max(0.0, score - _GLAUCOMA_PROCEDURE_PENALTY)

    return score


# ---------------------------------------------------------------------------
# Phase 1: Regulatory pre-score (non-PubMed track)
# ---------------------------------------------------------------------------

def _identifier_match(paper: Paper, query: str) -> float:
    """Return 1.0 if the paper's identifier appears verbatim in the query, else 0."""
    if not paper.identifier:
        return 0.0
    ident = paper.identifier.lower().strip()
    if not ident or len(ident) < 3:
        return 0.0
    return 1.0 if ident in query.lower() else 0.0


def prescore_regulatory(
    paper: Paper,
    query: str,
    target_product: TargetProductProfile | None,
) -> float:
    """Deterministic relevance pre-score in [0, 1] for regulatory records.

    Uses renormalised weights that do not penalise the absence of an abstract
    or MeSH headings, which regulatory records routinely lack.  The profile-
    signal component is dominant (0.55) because product-identity overlap is
    the strongest signal available for these records.
    """
    query_tokens = _tokenize(query)
    title_tokens = _tokenize(paper.title or "")

    signals = {
        "query_title": _recall(query_tokens, title_tokens),
        "profile_signal": _profile_signal(paper, target_product),
        "identifier_match": _identifier_match(paper, query),
    }

    score = sum(signals[k] * _REGULATORY_PRE_WEIGHTS[k] for k in signals)
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Anchor detection (literature track only)
# ---------------------------------------------------------------------------

_MAX_ANCHORS = 10


def detect_anchors(
    papers: list[Paper],
    target_product: TargetProductProfile | None,
    query: str = "",
) -> set[str]:
    """Return UIDs of papers whose title contains the target drug/device name.

    These papers are guaranteed inclusion regardless of LLM scoring.

    When the product name is generic (e.g. "intraocular lens"), a simple name
    match produces too many anchors. To prevent anchor flooding we cap the set
    at ``_MAX_ANCHORS``.  Within that cap we prefer papers whose title also
    contains a query keyword (3+ chars) — this biases anchors toward topically
    relevant papers rather than random product-name matches.
    """
    names = _anchor_names(target_product)
    if not names:
        return set()

    query_tokens = {
        t.lower() for t in query.split() if len(t) > 2
    }

    scored: list[tuple[str, int]] = []
    for p in papers:
        uid = p.uid
        if not uid:
            continue
        title_lower = (p.title or "").lower()
        if not any(name in title_lower for name in names):
            continue
        overlap = sum(1 for tok in query_tokens if tok in title_lower)
        scored.append((uid, overlap))

    scored.sort(key=lambda x: x[1], reverse=True)
    return {uid for uid, _ in scored[:_MAX_ANCHORS]}


# ---------------------------------------------------------------------------
# Phase 2: LLM relevance scoring — literature prompt
# ---------------------------------------------------------------------------

_TRIAGE_SYSTEM = """You are a medical evidence relevance scorer for regulatory submissions.
Given a search query and target product profile, score EVERY item below
for relevance on a 0-10 integer scale.

Items come from PubMed clinical literature. Score them on how well they
support an FDA regulatory submission for the described product/drug/device.

Scoring rubric:
 10 — Directly about this exact product/drug/device AND the exact indication.
  8 — Same drug/device class and same clinical domain; strong match.
  6 — Related clinical domain or product category, clearly usable evidence.
  4 — Tangentially related; some overlap with the indication or product.
  2 — Weak overlap, different population or product.
  0 — Completely irrelevant.

If USER METRICS OF INTEREST are listed in the query block, add weight to
papers that explicitly report quantitative values for those metrics (numeric
values with clinical units such as mmHg, %, logMAR, etc.).  A paper that
matches the device class AND reports a relevant numeric outcome should score
at least 2 points higher than one that matches only the device class.

Output format:
- One line per item: ID<tab>SCORE  (use the value shown after ID= on each line, then the score).
- Include EVERY item. Do not skip any.
- Order from highest score to lowest.
- No markdown, no labels, no code fences, no JSON."""


# ---------------------------------------------------------------------------
# Phase 2: LLM relevance scoring — regulatory prompt
# ---------------------------------------------------------------------------

_REGULATORY_TRIAGE_SYSTEM = """You are a regulatory document relevance scorer for FDA submissions.
Given a search query and target product profile, score EVERY item below
for relevance on a 0-10 integer scale.

These records come from regulatory databases: openFDA (510(k) clearances, drug labels,
adverse events), ClinicalTrials.gov (study registrations), DailyMed (drug labeling),
and AccessGUDID (device identifiers).

IMPORTANT: These records do NOT have clinical study abstracts or MeSH headings.
Do NOT penalise them for lacking those. Score them on what they do contain:
product identity, regulatory pathway, indication, and device/drug description.

Score based on:
- How well the product/device/drug identity matches the query and target profile
- Whether the regulatory pathway or indication is relevant
- Whether the record is about the same product class or a direct predicate/comparator

Scoring rubric:
 10 — Exact product/510(k)/label for this drug or device and indication.
  8 — Same product family, same regulatory pathway, or a close predicate device.
  6 — Same device/drug class or overlapping indication — clearly relevant.
  4 — Tangential overlap — different formulation, route, or indication but related.
  2 — Weak connection — same broad therapeutic area, different product type.
  0 — Completely irrelevant to the query.

Output format:
- One line per item: ID<tab>SCORE  (use the value shown after ID= on each line, then the score).
- Include EVERY item. Do not skip any.
- Order from highest score to lowest.
- No markdown, no labels, no code fences, no JSON."""


def _target_profile_summary(tp: TargetProductProfile | None) -> str:
    if tp is None:
        return "(none — use the query only)"
    parts: list[str] = []
    parts.append(f"target_type: {tp.target_type}")
    for name, val in (
        ("product_name", tp.product_name),
        ("device_category", tp.device_category),
        ("manufacturer", tp.manufacturer),
        ("intended_use", tp.intended_use),
        ("anatomical_site", tp.anatomical_site),
        ("material", tp.material),
        ("material_family", tp.material_family),
        ("material_subtype", tp.material_subtype),
        ("energy_source", tp.energy_source),
        ("device_class", tp.device_class),
        ("sterilization_method", tp.sterilization_method),
        ("active_ingredient", tp.active_ingredient),
        ("drug_class", tp.drug_class),
        ("route", tp.route),
    ):
        if val:
            parts.append(f"{name}: {val}")
    if tp.indications:
        parts.append("indications: " + "; ".join(tp.indications))
    if tp.key_features:
        parts.append("key_features: " + "; ".join(tp.key_features))
    if tp.material_features:
        parts.append("material_features: " + "; ".join(tp.material_features))
    return "\n".join(parts) if len(parts) > 1 else "(minimal profile)"


def _truncate_abstract(text: str | None) -> str:
    if not text:
        return ""
    t = text.strip().replace("\n", " ")
    if len(t) <= _ABSTRACT_MAX_LEN:
        return t
    return t[: _ABSTRACT_MAX_LEN - 3] + "..."


def _build_scoring_prompt(
    papers: list[Paper],
    query: str,
    target_product: TargetProductProfile | None,
    metrics_of_interest: list[str] | None = None,
) -> str:
    lines = [
        f"SEARCH QUERY:\n{query}\n",
        f"TARGET PRODUCT PROFILE:\n{_target_profile_summary(target_product)}\n",
    ]
    if metrics_of_interest:
        metric_lines = "\n".join(f"- {m}" for m in metrics_of_interest)
        lines.append(f"USER METRICS OF INTEREST:\n{metric_lines}\n")
    lines += [
        f"Score ALL {len(papers)} papers below on a 0-10 scale.\n",
        "PAPERS:",
    ]
    for p in papers:
        uid = p.uid
        title = (p.title or "").strip().replace("\n", " ")
        ab = _truncate_abstract(p.abstract)
        lines.append(f"ID={uid} | {title} | {ab}")
    return "\n".join(lines)


def _build_regulatory_scoring_prompt(
    papers: list[Paper],
    query: str,
    target_product: TargetProductProfile | None,
    metrics_of_interest: list[str] | None = None,
) -> str:
    lines = [
        f"SEARCH QUERY:\n{query}\n",
        f"TARGET PRODUCT PROFILE:\n{_target_profile_summary(target_product)}\n",
    ]
    if metrics_of_interest:
        metric_lines = "\n".join(f"- {m}" for m in metrics_of_interest)
        lines.append(f"USER METRICS OF INTEREST:\n{metric_lines}\n")
    lines += [
        f"Score ALL {len(papers)} regulatory records below on a 0-10 scale.\n",
        "REGULATORY RECORDS:",
    ]
    for p in papers:
        uid = p.uid
        title = (p.title or "").strip().replace("\n", " ")
        ab = _truncate_abstract(p.abstract)
        src = p.source or "unknown"
        entry = f"ID={uid} | SOURCE={src} | {title}"
        if ab:
            entry += f" | {ab}"
        lines.append(entry)
    return "\n".join(lines)


# Regex for "ID<whitespace or tab>SCORE" lines.
# Matches PMIDs (pure digits), NCT IDs, K-numbers, DM/GUDID/FDA_LABEL prefixed IDs.
_SCORED_LINE = re.compile(r"([\w:.-]{3,60})\s+(\d{1,2}(?:\.\d+)?)")


def _parse_scored_lines(raw: str, allowed: set[str]) -> dict[str, float]:
    """Parse LLM output into {uid: normalized_score_0_to_1}."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    scores: dict[str, float] = {}
    for line in text.split("\n"):
        m = _SCORED_LINE.search(line)
        if not m:
            continue
        uid = m.group(1)
        if uid not in allowed:
            continue
        raw_score = float(m.group(2))
        normalised = max(0.0, min(1.0, raw_score / 10.0))
        if uid not in scores:
            scores[uid] = normalised
    return scores


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
async def _call_scoring_llm(user_prompt: str, *, system: str = _TRIAGE_SYSTEM) -> str:
    cfg = get_llm_client_config()
    client = _get_client()
    response = await client.chat.completions.create(
        model=cfg.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=4096,
        **get_llm_extra_request_kwargs(),
    )
    return response.choices[0].message.content or ""


async def _stream_scoring_llm(user_prompt: str, *, system: str = _TRIAGE_SYSTEM):
    """Yield chat completion chunks from a streaming scoring call."""
    cfg = get_llm_client_config()
    client = _get_client()
    stream = await client.chat.completions.create(
        model=cfg.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=4096,
        stream=True,
        **get_llm_extra_request_kwargs(),
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


# ---------------------------------------------------------------------------
# Phase 3: Combined scoring & selection
# ---------------------------------------------------------------------------

@dataclass
class _ScoredPaper:
    uid: str
    source: str = _PUBMED_SOURCE
    pre_score: float = 0.0
    llm_score: float | None = None
    is_anchor: bool = False
    combined: float = 0.0

    def compute_combined(self) -> None:
        if self.llm_score is not None:
            self.combined = _PRE_SCORE_W * self.pre_score + _LLM_SCORE_W * self.llm_score
        else:
            self.combined = self.pre_score
        if self.is_anchor:
            self.combined = max(self.combined, _ANCHOR_FLOOR)


def _combine_and_select(
    scored: list[_ScoredPaper],
    top_n: int,
) -> list[str]:
    """Merge scores, guarantee anchor inclusion (capped at top_n), return top N UIDs."""
    for s in scored:
        s.compute_combined()
    scored.sort(key=lambda s: s.combined, reverse=True)

    selected: list[str] = []
    selected_set: set[str] = set()

    # Step 1: anchors — capped at top_n so they cannot consume all slots
    for s in scored:
        if len(selected) >= top_n:
            break
        if s.is_anchor and s.uid not in selected_set:
            selected.append(s.uid)
            selected_set.add(s.uid)

    # Step 2: fill remaining with top combined scores
    remaining = top_n - len(selected)
    for s in scored:
        if remaining <= 0:
            break
        if s.uid not in selected_set:
            selected.append(s.uid)
            selected_set.add(s.uid)
            remaining -= 1

    return _dedupe_preserve_order(selected)[:top_n]


def _fallback_uids(papers: list[Paper], top_n: int) -> list[str]:
    out: list[str] = []
    for p in papers:
        uid = p.uid
        if uid and uid not in out:
            out.append(uid)
        if len(out) >= top_n:
            break
    return out[:top_n]


# ---------------------------------------------------------------------------
# Internal single-track triage (batch LLM call)
# ---------------------------------------------------------------------------

async def _triage_track(
    papers: list[Paper],
    query: str,
    target_product: TargetProductProfile | None,
    top_n: int,
    *,
    regulatory: bool = False,
    metrics_of_interest: list[str] | None = None,
) -> list[str]:
    """Run the 3-phase triage pipeline on one source-homogeneous track.

    Returns up to *top_n* UIDs ordered by combined score.  Uses the
    literature pre-scorer and LLM prompt when *regulatory* is False, and
    the regulatory equivalents when True.
    """
    if not papers or top_n < 1:
        return []
    valid = [p for p in papers if p.uid]
    if not valid:
        return []
    if len(valid) <= top_n:
        return [p.uid for p in valid]

    # Phase 1: pre-score — compute metric signals once for all papers
    metric_cache: dict = {}
    pre_scores: dict[str, float] = {}
    for p in valid:
        if regulatory:
            pre_scores[p.uid] = prescore_regulatory(p, query, target_product)
        else:
            pre_scores[p.uid] = prescore_paper(
                p, query, target_product, metrics_of_interest, _metric_cache=metric_cache
            )

    # Anchor detection (literature track only)
    anchors: set[str] = set()
    if not regulatory:
        anchors = detect_anchors(valid, target_product, query=query)
        if anchors:
            logger.info("Triage anchors (literature, guaranteed): {}", anchors)

    # Build LLM shortlist: anchors + top papers by pre-score
    shortlist_size = min(
        len(valid),
        max(top_n * _LLM_SHORTLIST_FACTOR, len(anchors) + top_n),
    )
    sorted_by_pre = sorted(valid, key=lambda p: pre_scores.get(p.uid, 0.0), reverse=True)
    shortlist_uids: set[str] = set(anchors)
    for p in sorted_by_pre:
        shortlist_uids.add(p.uid)
        if len(shortlist_uids) >= shortlist_size:
            break

    # Metric-hit quota: guarantee up to min(top_n//2, 10) slots for papers
    # with strong metric signal that would otherwise fall outside the shortlist.
    if metrics_of_interest and not regulatory:
        metric_quota = min(top_n // 2, 10)
        quota_candidates = sorted(
            [p for p in valid if p.uid not in shortlist_uids],
            key=lambda p: metric_cache.get(p.uid, _metric_signal(p, metrics_of_interest)),
            reverse=True,
        )
        added = 0
        for p in quota_candidates:
            sig = metric_cache.get(p.uid, 0.0)
            if sig < 0.35:
                break
            shortlist_uids.add(p.uid)
            added += 1
            if added >= metric_quota:
                break
        if added:
            logger.info("Metric-hit quota added {} papers to triage shortlist", added)

    shortlist_papers = [p for p in valid if p.uid in shortlist_uids]

    # Phase 2: LLM scoring on shortlist
    llm_scores: dict[str, float] = {}
    if len(shortlist_papers) > top_n:
        allowed = {p.uid for p in shortlist_papers}
        system_prompt = _REGULATORY_TRIAGE_SYSTEM if regulatory else _TRIAGE_SYSTEM
        prompt_fn = _build_regulatory_scoring_prompt if regulatory else _build_scoring_prompt
        prompt = prompt_fn(shortlist_papers, query, target_product, metrics_of_interest)
        try:
            raw = await _call_scoring_llm(prompt, system=system_prompt)
            llm_scores = _parse_scored_lines(raw, allowed)
        except Exception as exc:
            logger.warning(
                "Triage LLM scoring failed (regulatory={}), using pre-scores only: {}",
                regulatory,
                exc,
            )

    # Phase 3: combine and select
    scored = [
        _ScoredPaper(
            uid=p.uid,
            source=p.source,
            pre_score=pre_scores.get(p.uid, 0.0),
            llm_score=llm_scores.get(p.uid),
            is_anchor=(p.uid in anchors),
        )
        for p in valid
    ]
    result = _combine_and_select(scored, top_n)
    logger.info(
        "Triage track (regulatory={}) selected {} from {} (anchors={}, llm_scored={})",
        regulatory,
        len(result),
        len(valid),
        len(anchors),
        len(llm_scores),
    )
    return result


# ---------------------------------------------------------------------------
# Internal single-track triage (streaming LLM call)
# ---------------------------------------------------------------------------

async def _triage_track_stream(
    papers: list[Paper],
    query: str,
    target_product: TargetProductProfile | None,
    top_n: int,
    *,
    regulatory: bool = False,
    metrics_of_interest: list[str] | None = None,
) -> list[str]:
    """Same as _triage_track but uses the streaming LLM endpoint internally.

    Collects all streamed scores before running Phase 3 — the streaming is
    done to lower time-to-first-token on the LLM side, not to progressively
    yield UIDs to the caller.
    """
    if not papers or top_n < 1:
        return []
    valid = [p for p in papers if p.uid]
    if not valid:
        return []
    if len(valid) <= top_n:
        return [p.uid for p in valid]

    # Phase 1: pre-score — compute metric signals once for all papers
    metric_cache: dict = {}
    pre_scores: dict[str, float] = {}
    for p in valid:
        if regulatory:
            pre_scores[p.uid] = prescore_regulatory(p, query, target_product)
        else:
            pre_scores[p.uid] = prescore_paper(
                p, query, target_product, metrics_of_interest, _metric_cache=metric_cache
            )

    anchors: set[str] = set()
    if not regulatory:
        anchors = detect_anchors(valid, target_product, query=query)

    shortlist_size = min(
        len(valid),
        max(top_n * _LLM_SHORTLIST_FACTOR, len(anchors) + top_n),
    )
    sorted_by_pre = sorted(valid, key=lambda p: pre_scores.get(p.uid, 0.0), reverse=True)
    shortlist_uids: set[str] = set(anchors)
    for p in sorted_by_pre:
        shortlist_uids.add(p.uid)
        if len(shortlist_uids) >= shortlist_size:
            break

    # Metric-hit quota
    if metrics_of_interest and not regulatory:
        metric_quota = min(top_n // 2, 10)
        quota_candidates = sorted(
            [p for p in valid if p.uid not in shortlist_uids],
            key=lambda p: metric_cache.get(p.uid, _metric_signal(p, metrics_of_interest)),
            reverse=True,
        )
        added = 0
        for p in quota_candidates:
            sig = metric_cache.get(p.uid, 0.0)
            if sig < 0.35:
                break
            shortlist_uids.add(p.uid)
            added += 1
            if added >= metric_quota:
                break

    shortlist_papers = [p for p in valid if p.uid in shortlist_uids]

    if len(shortlist_papers) <= top_n:
        # Small enough to skip LLM
        scored = [
            _ScoredPaper(
                uid=p.uid,
                source=p.source,
                pre_score=pre_scores.get(p.uid, 0.0),
                llm_score=None,
                is_anchor=(p.uid in anchors),
            )
            for p in valid
        ]
        return _combine_and_select(scored, top_n)

    # Phase 2: streaming LLM scoring
    allowed = {p.uid for p in shortlist_papers}
    system_prompt = _REGULATORY_TRIAGE_SYSTEM if regulatory else _TRIAGE_SYSTEM
    prompt_fn = _build_regulatory_scoring_prompt if regulatory else _build_scoring_prompt
    prompt = prompt_fn(shortlist_papers, query, target_product, metrics_of_interest)

    llm_scores: dict[str, float] = {}
    buf = ""
    try:
        async for piece in _stream_scoring_llm(prompt, system=system_prompt):
            buf += piece
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                m = _SCORED_LINE.search(line)
                if m and m.group(1) in allowed:
                    uid = m.group(1)
                    raw_score = float(m.group(2))
                    llm_scores[uid] = max(0.0, min(1.0, raw_score / 10.0))
        if buf.strip():
            m = _SCORED_LINE.search(buf)
            if m and m.group(1) in allowed:
                uid = m.group(1)
                raw_score = float(m.group(2))
                llm_scores[uid] = max(0.0, min(1.0, raw_score / 10.0))
    except Exception as exc:
        logger.warning("Triage stream scoring failed (regulatory={}): {}", regulatory, exc)

    # Phase 3
    scored = [
        _ScoredPaper(
            uid=p.uid,
            source=p.source,
            pre_score=pre_scores.get(p.uid, 0.0),
            llm_score=llm_scores.get(p.uid),
            is_anchor=(p.uid in anchors),
        )
        for p in valid
    ]
    return _combine_and_select(scored, top_n)


# ---------------------------------------------------------------------------
# Slot allocation helper
# ---------------------------------------------------------------------------

def _allocate_slots(
    n_lit: int,
    n_reg: int,
    top_n: int,
) -> tuple[int, int]:
    """Return (lit_slots, reg_slots) given pool sizes and total budget."""
    if n_reg == 0:
        return top_n, 0
    if n_lit == 0:
        return 0, top_n
    reg_slots = max(1, math.ceil(top_n * _REGULATORY_SLOT_FRACTION))
    reg_slots = min(reg_slots, n_reg, top_n - 1)
    lit_slots = top_n - reg_slots
    return lit_slots, reg_slots


# ---------------------------------------------------------------------------
# Public API — batch
# ---------------------------------------------------------------------------

async def triage_papers(
    papers: list[Paper],
    query: str,
    target_product: TargetProductProfile | None,
    top_n: int,
    metrics_of_interest: list[str] | None = None,
) -> list[str]:
    """Return the top_n most relevant UIDs via split-track hybrid triage.

    Literature (PubMed) and regulatory (openFDA / ClinicalTrials / DailyMed /
    AccessGUDID) papers are triaged independently with source-appropriate
    pre-scoring and LLM prompts, then merged.  Slots are allocated 70 / 30
    when both tracks are populated.  Surplus from an under-populated track
    spills over to the other.
    """
    if top_n < 1:
        return []
    valid = [p for p in papers if p.uid]
    if not valid:
        return []
    if len(valid) <= top_n:
        return [p.uid for p in valid]

    lit_papers = [p for p in valid if p.source not in _REGULATORY_SOURCES]
    reg_papers = [p for p in valid if p.source in _REGULATORY_SOURCES]

    lit_slots, reg_slots = _allocate_slots(len(lit_papers), len(reg_papers), top_n)
    logger.info(
        "Triage split: lit_papers={}, reg_papers={}, lit_slots={}, reg_slots={}",
        len(lit_papers),
        len(reg_papers),
        lit_slots,
        reg_slots,
    )

    lit_uids = (
        await _triage_track(lit_papers, query, target_product, lit_slots, metrics_of_interest=metrics_of_interest)
        if lit_slots > 0 else []
    )
    reg_uids = (
        await _triage_track(reg_papers, query, target_product, reg_slots, regulatory=True)
        if reg_slots > 0 else []
    )

    # Handle underflow: if one track delivers fewer than its allocation,
    # fill surplus from the other (one extra call, capped).
    lit_deficit = lit_slots - len(lit_uids)
    reg_deficit = reg_slots - len(reg_uids)

    if reg_deficit > 0 and lit_papers and lit_slots < len(lit_papers):
        extra = await _triage_track(
            lit_papers, query, target_product, lit_slots + reg_deficit,
            metrics_of_interest=metrics_of_interest,
        )
        lit_set = set(lit_uids)
        for uid in extra:
            if uid not in lit_set and len(lit_uids) < lit_slots + reg_deficit:
                lit_uids.append(uid)

    if lit_deficit > 0 and reg_papers and reg_slots < len(reg_papers):
        extra = await _triage_track(reg_papers, query, target_product, reg_slots + lit_deficit, regulatory=True)
        reg_set = set(reg_uids)
        for uid in extra:
            if uid not in reg_set and len(reg_uids) < reg_slots + lit_deficit:
                reg_uids.append(uid)

    # Merge: literature first, then regulatory, deduped
    result: list[str] = []
    seen: set[str] = set()
    for uid in lit_uids + reg_uids:
        if uid not in seen:
            seen.add(uid)
            result.append(uid)

    logger.info(
        "Triage final: {} selected (lit={}, reg={})",
        len(result),
        len(lit_uids),
        len(reg_uids),
    )
    return result[:top_n]


# ---------------------------------------------------------------------------
# Public API — streaming
# ---------------------------------------------------------------------------

async def triage_papers_stream(
    papers: list[Paper],
    query: str,
    target_product: TargetProductProfile | None,
    top_n: int,
    metrics_of_interest: list[str] | None = None,
) -> AsyncIterator[str]:
    """Yield shortlisted UIDs in final hybrid-rank order.

    Uses the same split-track logic as ``triage_papers`` but drives the LLM
    via streaming internally to reduce latency.
    """
    if top_n < 1:
        return
    valid = [p for p in papers if p.uid]
    if not valid:
        return
    if len(valid) <= top_n:
        for p in valid:
            yield p.uid
        return

    lit_papers = [p for p in valid if p.source not in _REGULATORY_SOURCES]
    reg_papers = [p for p in valid if p.source in _REGULATORY_SOURCES]

    lit_slots, reg_slots = _allocate_slots(len(lit_papers), len(reg_papers), top_n)

    lit_uids = (
        await _triage_track_stream(
            lit_papers, query, target_product, lit_slots,
            metrics_of_interest=metrics_of_interest,
        )
        if lit_slots > 0
        else []
    )
    reg_uids = (
        await _triage_track_stream(reg_papers, query, target_product, reg_slots, regulatory=True)
        if reg_slots > 0
        else []
    )

    # Underflow handling (mirrors batch version)
    lit_deficit = lit_slots - len(lit_uids)
    reg_deficit = reg_slots - len(reg_uids)

    if reg_deficit > 0 and lit_papers and lit_slots < len(lit_papers):
        extra = await _triage_track_stream(
            lit_papers, query, target_product, lit_slots + reg_deficit,
            metrics_of_interest=metrics_of_interest,
        )
        lit_set = set(lit_uids)
        for uid in extra:
            if uid not in lit_set and len(lit_uids) < lit_slots + reg_deficit:
                lit_uids.append(uid)

    if lit_deficit > 0 and reg_papers and reg_slots < len(reg_papers):
        extra = await _triage_track_stream(
            reg_papers, query, target_product, reg_slots + lit_deficit, regulatory=True
        )
        reg_set = set(reg_uids)
        for uid in extra:
            if uid not in reg_set and len(reg_uids) < reg_slots + lit_deficit:
                reg_uids.append(uid)

    seen: set[str] = set()
    for uid in lit_uids + reg_uids:
        if uid not in seen:
            seen.add(uid)
            yield uid
        if len(seen) >= top_n:
            return
