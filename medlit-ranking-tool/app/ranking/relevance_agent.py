"""LLM-based semantic relevance scoring, blended with deterministic recency.

Falls back to ``score_relevance`` (keyword + topical label + recency) on failure.
"""

from __future__ import annotations

import json

from loguru import logger
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_llm_client_config, get_llm_extra_request_kwargs
from app.models.extraction import ExtractionResult
from app.models.paper import Paper
from app.models.search import SearchRequest, TargetProductProfile
from app.ranking.relevance import recency_component, score_relevance

_LLM_BLEND = 0.9
_RECENCY_BLEND = 0.1

_RELEVANCE_SYSTEM = """You are a medical literature relevance scorer.
Given a PubMed paper (title + abstract), a user search query, and an optional target product profile,
output a single JSON object with:
- "score": float from 0.0 to 1.0 meaning how well this paper matches the user's evidence need.
- "rationale": one short sentence (max 200 chars).

Rubric (approximate):
- 0.9–1.0: Directly addresses the same device/drug, indication, or comparison the user needs.
- 0.7–0.89: Same clinical domain and clearly usable evidence, but not a perfect match.
- 0.5–0.69: Tangentially related or mixed relevance.
- Below 0.5: Off-topic, wrong population, or not useful for the stated goal.

Return ONLY valid JSON. No markdown fences, no extra keys."""


def _get_client() -> AsyncOpenAI:
    c = get_llm_client_config()
    return AsyncOpenAI(
        api_key=c.api_key,
        base_url=c.base_url,
        timeout=120.0,
    )


def _profile_lines(tp: TargetProductProfile | None) -> str:
    if tp is None:
        return "(none)"
    parts: list[str] = []
    if tp.product_name:
        parts.append(f"product_name: {tp.product_name}")
    if tp.device_category:
        parts.append(f"device_category: {tp.device_category}")
    if tp.intended_use:
        parts.append(f"intended_use: {tp.intended_use}")
    if tp.indications:
        parts.append("indications: " + "; ".join(tp.indications))
    if tp.active_ingredient:
        parts.append(f"active_ingredient: {tp.active_ingredient}")
    return "\n".join(parts) if parts else "(minimal)"


def _build_user_prompt(paper: Paper, request: SearchRequest) -> str:
    title = (paper.title or "").strip()
    abstract = (paper.abstract or "").strip()
    q = request.query.strip()
    prof = _profile_lines(request.target_product)
    return (
        f"USER QUERY:\n{q}\n\n"
        f"TARGET PRODUCT PROFILE:\n{prof}\n\n"
        f"TITLE:\n{title}\n\n"
        f"ABSTRACT:\n{abstract[:8000]}\n"
    )


def _parse_json(raw: str) -> tuple[float, str]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    score = float(data.get("score", 0.0))
    rationale = str(data.get("rationale", ""))[:500]
    score = max(0.0, min(1.0, score))
    return score, rationale


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
async def _call_relevance_llm(user_prompt: str) -> str:
    cfg = get_llm_client_config()
    client = _get_client()
    response = await client.chat.completions.create(
        model=cfg.model,
        messages=[
            {"role": "system", "content": _RELEVANCE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=512,
        **get_llm_extra_request_kwargs(),
    )
    return response.choices[0].message.content or ""


async def llm_relevance_raw(paper: Paper, request: SearchRequest) -> tuple[float, dict] | None:
    """Return LLM semantic score and breakdown, or None on any failure."""
    try:
        raw = await _call_relevance_llm(_build_user_prompt(paper, request))
        score, rationale = _parse_json(raw)
        return score, {
            "llm_score": score,
            "rationale": rationale,
            "method": "llm",
        }
    except Exception as exc:
        logger.warning("LLM relevance failed: {}", exc)
        return None


def merge_relevance_llm(
    llm: tuple[float, dict] | None,
    paper: Paper,
    extracted: ExtractionResult,
    request: SearchRequest,
) -> tuple[float, dict]:
    """Blend LLM score with recency, or fall back to deterministic ``score_relevance``."""
    if llm is not None:
        s, bd = llm
        llm_s = float(bd.get("llm_score", s))
        rec = recency_component(paper)
        r = max(0.0, min(1.0, _LLM_BLEND * llm_s + _RECENCY_BLEND * rec))
        out = {
            **bd,
            "recency": rec,
            "blend_weights": {"llm": _LLM_BLEND, "recency": _RECENCY_BLEND},
            "method": "llm_recency_blend",
        }
        return r, out
    return score_relevance(paper, extracted, request)

