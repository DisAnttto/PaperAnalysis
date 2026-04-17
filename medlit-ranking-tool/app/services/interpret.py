"""Natural-language finding parser — two-step light-model chain."""

from __future__ import annotations

import json
import re

from loguru import logger
from openai import AsyncOpenAI

from app.core.config import (
    get_llm_extra_request_kwargs,
    get_llm_light_config,
)
from app.models.interpret import FindingParseResponse

# ---------------------------------------------------------------------------
# Step 1 — Context & intent extraction (translation + summarisation)
# ---------------------------------------------------------------------------

_STEP1_SYSTEM = """\
You are a medical research assistant. The user will paste a research brief
that may be in any language (often Chinese). Your ONLY job is to understand
it and summarise it in English as a JSON object.

Return a JSON object with exactly these keys:

"product_context" (object or null) — the product/intervention described:
  "name"         — product name in English (e.g. "intraocular lens", "AcrySof IQ")
  "name_source"  — short product phrase EXACTLY as the user wrote it in their
                   language (e.g. 人工晶状体, 爱博诺德人工晶状体). Required when
                   a product is mentioned — preserves UI display in source script.
  "type"         — "device", "drug", or "both"
  "manufacturer" — company name in English
  "category"     — device category in snake_case (e.g. "intraocular_lens")
  "intended_use" — short phrase
  "indications"  — array of condition names in English
  "procedure"    — surgical/administration procedure if mentioned
  "active_ingredient" — for drugs (null for devices)
  "drug_class"        — for drugs (null for devices)
  "route"             — administration route (null for devices)

"clinical_finding" (object or null) — any numeric result reported:
  "metric"       — standard English abbreviation (e.g. "IOP", "BCVA")
  "unit"         — e.g. "mmHg", "logMAR"
  "timepoint"    — normalised (e.g. "POD1", "Month 3")
  "observed"     — test/experimental group value (number)
  "control"      — control/baseline value (number or null)
  "significant"  — true/false/null

"search_goals" (array of strings) — 1-5 English sentences, each describing
  one type of paper the user wants to find. MUST include every distinct
  literature request (e.g. numbered items like "搜集1…2…3…"). Translate and
  interpret the user's intent. Example:
  ["Papers reporting transient IOP elevation after cataract surgery that normalises long-term",
   "Papers where postoperative IOP is around 20 mmHg",
   "Papers arguing that IOP of 20 mmHg is within safe limits"]

"seed_identifier" (str or null) — ONLY if an explicit record ID appears
  (PMID:xxx, K-number, NCT, DEN). Never invent one.

Normalisation rules:
- Translate ALL Chinese medical terms to standard English.
- 眼压/眼内压 → "IOP"; 视力/BCVA → "BCVA"; 术后1天 → "POD1"
- Company names: 爱博诺德 → "Eyebright Medical"; 爱尔康 → "Alcon"

Return ONLY the JSON — no markdown fences, no explanation.\
"""

# ---------------------------------------------------------------------------
# Step 2 — Search field generation (structured → SearchRequest fields)
# ---------------------------------------------------------------------------

_STEP2_SYSTEM = """\
You are a PubMed search strategist. You will receive a JSON object containing
product_context, clinical_finding, search_goals, and seed_identifier — all in
English, pre-extracted from a user's research brief.

Your job: generate the BEST search parameters for a medical literature search.

Return ONLY a JSON object with these keys (null for absent fields):

"query"              (str)   — PubMed keyword query, 5-12 terms. This MUST
                               capture the search_goals, NOT just echo the
                               product name. Combine: clinical topic + what
                               papers to find. Example: "intraocular pressure
                               postoperative cataract surgery transient
                               elevation safety normal range"
"seed_identifier"    (str)   — pass through from input, or null
"keywords"           (array) — broad PubMed RETRIEVAL terms: condition
                               synonyms, related procedures, clinical setting
                               variants. These are ORed together to EXPAND the
                               pool, so each entry should independently match
                               useful papers. Rules:
                               • DO NOT include specific numeric values such as
                                 "20 mmHg", "18 mmHg", "21 mmHg", ">25 mmHg" —
                                 numeric thresholds go in metrics_of_interest.
                               • DO NOT use short abbreviations that rarely appear
                                 in titles (e.g. "POD1") — spell out the concept
                                 ("postoperative day 1", "first postoperative day").
                               • DO NOT repeat terms already in query.
                               • Keep each keyword SHORT: 1-3 words preferred,
                                 max 3 content words. PubMed phrase-searches
                                 exact multi-word strings — long phrases fail.
                               • Include subgroup terms the user mentions
                                 (e.g. "glaucoma", "pseudoexfoliation").
                               Good examples: ["IOP spike", "transient IOP",
                                 "ocular hypertension", "phacoemulsification",
                                 "glaucoma", "pseudoexfoliation",
                                 "postoperative IOP"].
"target_type"        (str)   — "device", "drug", or "both". Use "device" when
                               the product is clearly a medical device: lens,
                               implant, stent, catheter, electrode, scaffold.
                               Only use "both" when the product is genuinely
                               ambiguous (e.g. a drug-eluting stent).
"product_name"       (str)   — brand/model name
"manufacturer"       (str)   — company name in English
"device_category"    (str)   — snake_case
"intended_use"       (str)   — short phrase
"indications"        (array) — condition names AND related surgical procedures.
                               For cataract/IOL, include both the condition
                               (e.g. "cataract", "aphakia") AND the procedure
                               (e.g. "phacoemulsification", "cataract surgery").
"active_ingredient"  (str)   — for drugs
"drug_class"         (str)   — for drugs
"route"              (str)   — administration route
"metrics_of_interest"(array) — clinical endpoints qualified with values and
                               context when available. Instead of bare "IOP",
                               write "IOP ~20 mmHg postoperative" or
                               "transient IOP spike". Instead of bare "BCVA",
                               write "BCVA improvement near/intermediate".
                               Each entry should be a short phrase (2-6 words)
                               that a researcher would recognise as a specific
                               search-relevant metric target.
"metric_name"        (str)   — primary metric abbreviation (from finding)
"metric_unit"        (str)   — unit
"timepoint"          (str)   — normalised timepoint
"observed_value"     (number)— experimental group value
"control_value"      (number)— control group value
"is_significant"     (bool)  — true/false/null
"clinical_context"   (str)   — e.g. "cataract surgery"
"procedure"          (str)   — e.g. "phacoemulsification"

Key rules:
- query MUST reflect search_goals — what papers to find — not product metadata.
- keywords are broad PubMed recall boosters. DO NOT put numeric values (mmHg,
  %, etc.) or short abbreviations (POD1) in keywords — those belong in
  metrics_of_interest or nowhere.
- metrics_of_interest: qualify each metric with value/context from the finding
  and search_goals — not bare abbreviations. E.g. "IOP ~20 mmHg postoperative".
- target_type: "device" for any implant/lens/stent/catheter/electrode. Only
  "both" when genuinely ambiguous. Default "both" only as last resort.

Return ONLY the JSON — no markdown fences, no explanation.\
"""


def _strip_fences(raw: str) -> str:
    """Remove optional markdown code fences from LLM output."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw


def _list_or_none(val: object) -> list[str] | None:
    if isinstance(val, list):
        return [str(v) for v in val] or None
    return None


def _step1_preview_kwargs(step1: dict | None) -> dict:
    """Fields echoed to the client so the UI can show specs vs intent vs finding."""
    if not step1:
        return {
            "step1_product_context": None,
            "step1_clinical_finding": None,
            "step1_search_goals": None,
        }
    pc = step1.get("product_context")
    cf = step1.get("clinical_finding")
    return {
        "step1_product_context": pc if isinstance(pc, dict) else None,
        "step1_clinical_finding": cf if isinstance(cf, dict) else None,
        "step1_search_goals": _list_or_none(step1.get("search_goals")),
    }


def _build_response(data: dict, raw_text: str, step1: dict | None = None) -> FindingParseResponse:
    """Map a flat dict of search fields into a FindingParseResponse."""
    return FindingParseResponse(
        metric_name=data.get("metric_name"),
        metric_unit=data.get("metric_unit"),
        timepoint=data.get("timepoint"),
        observed_value=data.get("observed_value"),
        control_value=data.get("control_value"),
        is_significant=data.get("is_significant"),
        clinical_context=data.get("clinical_context"),
        procedure=data.get("procedure"),
        query=data.get("query"),
        target_type=data.get("target_type"),
        product_name=data.get("product_name"),
        manufacturer=data.get("manufacturer"),
        device_category=data.get("device_category"),
        intended_use=data.get("intended_use"),
        indications=_list_or_none(data.get("indications")),
        active_ingredient=data.get("active_ingredient"),
        drug_class=data.get("drug_class"),
        route=data.get("route"),
        metrics_of_interest=_list_or_none(data.get("metrics_of_interest")),
        seed_identifier=data.get("seed_identifier") or None,
        keywords=_list_or_none(data.get("keywords")),
        raw_text=raw_text,
        **_step1_preview_kwargs(step1),
    )


def _partial_from_step1(ctx: dict, raw_text: str) -> FindingParseResponse:
    """Best-effort mapping when Step 2 fails but Step 1 succeeded."""
    product = ctx.get("product_context") or {}
    finding = ctx.get("clinical_finding") or {}
    goals = ctx.get("search_goals") or []

    query = " ".join(goals[0].split()[:12]) if goals else None

    return FindingParseResponse(
        query=query,
        target_type=product.get("type"),
        product_name=product.get("name"),
        manufacturer=product.get("manufacturer"),
        device_category=product.get("category"),
        intended_use=product.get("intended_use"),
        indications=_list_or_none(product.get("indications")),
        active_ingredient=product.get("active_ingredient"),
        drug_class=product.get("drug_class"),
        route=product.get("route"),
        procedure=product.get("procedure"),
        metric_name=finding.get("metric"),
        metric_unit=finding.get("unit"),
        timepoint=finding.get("timepoint"),
        observed_value=finding.get("observed"),
        control_value=finding.get("control"),
        is_significant=finding.get("significant"),
        metrics_of_interest=[finding["metric"]] if finding.get("metric") else None,
        seed_identifier=ctx.get("seed_identifier"),
        raw_text=raw_text,
        **_step1_preview_kwargs(ctx),
    )


async def parse_finding_text(text: str) -> FindingParseResponse:
    """Two-step LLM chain: extract context + intent, then generate search fields.

    Step 1 (light model): translate/summarise the raw input into an English
    intermediate with product_context, clinical_finding, and search_goals.

    Step 2 (light model): convert the intermediate into final SearchRequest-
    compatible fields (PubMed query, keywords, profile, metrics).

    Falls back gracefully: Step 1 failure → empty response; Step 2 failure →
    partial fields from Step 1.
    """
    cfg = get_llm_light_config()
    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    extra = get_llm_extra_request_kwargs()

    # ── Step 1: context + intent extraction ──────────────────────────────
    try:
        resp1 = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": _STEP1_SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=512,
            **extra,
        )
        raw1 = _strip_fences((resp1.choices[0].message.content or "").strip())
        step1 = json.loads(raw1)
    except Exception as exc:
        logger.warning("Step 1 (context extraction) failed: {}", exc)
        return FindingParseResponse(raw_text=text)

    # ── Step 2: search field generation ──────────────────────────────────
    try:
        resp2 = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {"role": "system", "content": _STEP2_SYSTEM},
                {"role": "user", "content": json.dumps(step1, ensure_ascii=False)},
            ],
            temperature=0.1,
            max_tokens=512,
            **extra,
        )
        raw2 = _strip_fences((resp2.choices[0].message.content or "").strip())
        data = json.loads(raw2)
    except Exception as exc:
        logger.warning("Step 2 (field generation) failed, using Step 1 fallback: {}", exc)
        return _partial_from_step1(step1, raw_text=text)

    return _build_response(data, raw_text=text, step1=step1)
