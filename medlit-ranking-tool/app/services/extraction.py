"""LLM-based structured extraction from paper title + abstract.

Uses the OpenAI-compatible API (works with Qwen/DashScope, OpenAI, or any
compatible provider).  The LLM returns JSON matching ExtractionResult; Pydantic
validates the output.

Retry logic via tenacity handles transient API failures.
"""

import json

from loguru import logger
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_llm_client_config, get_llm_extra_request_kwargs
from app.models.extraction import ExtractionResult
from app.models.paper import Paper

_SYSTEM_PROMPT = """\
You are a medical literature extraction assistant specializing in ophthalmology.
Given a paper's title and abstract, you MUST produce a single JSON object that
matches the schema below EXACTLY.  Follow these rules strictly:

RULES:
1. Every field that cannot be determined from the text MUST be null — never omit it.
2. Every non-null extracted value MUST include an "evidence_snippet" copied
   verbatim from the source text, and an "evidence_section" ("title" or "abstract").
3. If the paper describes a medical device, populate the "device" object.
   If drug, populate "drug". If both, populate both. If neither is clearly
   described, set both to null.  NEVER fabricate an empty section.
4. "study_type" must be one of: systematic_review, meta_analysis, rct,
   prospective_cohort, retrospective_cohort, case_control, case_series,
   case_report, bench_study, in_vitro_study, animal_study, narrative_review, unknown.
5. "evidence_domain" must be one of: human_clinical, animal, in_vitro, bench, mixed, unknown.
6. "topical_relevance.label" must be one of: high, medium, low — based on how
   relevant the paper is to ophthalmology medical device/drug evidence.
7. "metric_category" must be one of: safety, efficacy, performance, durability,
   biocompatibility, toxicity, adverse_event, pharmacokinetics, pharmacodynamics, other.
8. "value_type" must be one of: numeric, range, percentage, binary, text.
   - numeric/percentage: requires numeric_value (and unit for percentage)
   - range: requires value_min and value_max
   - text: requires text_value
   - binary: text_value must be "yes", "no", or "unclear"
9. Regulatory approval status must NEVER be inferred — only report what is
   explicitly stated.  Omit the "regulatory" field entirely from your output.
10. Return ONLY the JSON object.  No markdown, no explanation, no code fences.

EXACT STRUCTURE FOR "metrics" ARRAY ITEMS (all fields shown; omit numeric fields not relevant):
{
  "metric_name_normalized": "<short canonical name e.g. best_corrected_visual_acuity>",
  "metric_name_raw": "<exact text from paper>",
  "metric_category": "<one of the allowed values above>",
  "value_type": "<numeric|range|percentage|binary|text>",
  "numeric_value": <float or null>,
  "value_min": <float or null>,
  "value_max": <float or null>,
  "text_value": <string or null>,
  "unit": <string or null>,
  "confidence_interval_low": <float or null>,
  "confidence_interval_high": <float or null>,
  "p_value": <float or null>,
  "timepoint": <string or null>,
  "comparator": <string or null>,
  "evidence_snippet": "<verbatim excerpt>",
  "evidence_section": "<title|abstract>"
}

EXACT STRUCTURE FOR "qualitative_findings" ARRAY ITEMS:
{
  "tag": "<short keyword e.g. non_inferiority, adverse_event, comparison>",
  "status": "<present|absent|mixed|unclear>",
  "severity": <string or null>,
  "evidence_snippet": "<verbatim excerpt>",
  "evidence_section": "<title|abstract>"
}

OUTPUT SCHEMA (JSON):
{
  "schema_version": "1.0.0",
  "source_scope": "title_abstract",
  "pmid": <string or null>,
  "doi": <string or null>,
  "paper_synopsis": {
    "value": "<2-5 sentence synopsis>",
    "supporting_evidence_snippets": ["<verbatim excerpt>", ...]
  },
  "topical_relevance": {
    "label": "<high|medium|low>",
    "evidence_snippet": "<verbatim excerpt>",
    "evidence_section": "<title|abstract>"
  },
  "device": null | { ... },
  "drug": null | {
    "product_name": null | {"value": "...", "evidence_snippet": "...", "evidence_section": "..."},
    "active_ingredient": null | {"value": "...", "evidence_snippet": "...", "evidence_section": "..."},
    "drug_class": null | {"value": "...", "evidence_snippet": "...", "evidence_section": "..."},
    "route": null | {"value": "...", "evidence_snippet": "...", "evidence_section": "..."},
    "indications": null | {"value": ["..."], "evidence_snippet": "...", "evidence_section": "..."},
    "formulation_features": null | {"value": ["..."], "evidence_snippet": "...", "evidence_section": "..."}
  },
  "study": {
    "study_type": {"value": "...", "evidence_snippet": "...", "evidence_section": "..."},
    "evidence_domain": {"value": "...", "evidence_snippet": "...", "evidence_section": "..."},
    "sample_size": null | {"value": <int>, "evidence_snippet": "...", "evidence_section": "..."},
    "population_description": null | {"value": "...", "evidence_snippet": "...", "evidence_section": "..."},
    "follow_up_duration": null | {"value": "...", "evidence_snippet": "...", "evidence_section": "..."}
  },
  "metrics": [<use EXACT STRUCTURE above>],
  "qualitative_findings": [<use EXACT STRUCTURE above>],
  "extraction_warnings": []
}
"""


def _build_user_prompt(paper: Paper, metrics_of_interest: list[str] | None = None) -> str:
    parts = [f"TITLE: {paper.title}"]
    if paper.abstract:
        parts.append(f"\nABSTRACT: {paper.abstract}")
    if paper.pmid:
        parts.append(f"\nPMID: {paper.pmid}")
    if paper.doi:
        parts.append(f"\nDOI: {paper.doi}")
    if metrics_of_interest:
        metric_lines = "\n".join(f"  - {m}" for m in metrics_of_interest)
        parts.append(
            f"\nMETRICS OF INTEREST (extract these specifically if found in the text):\n"
            f"{metric_lines}\n"
            f"For each metric found, use the exact name from this list as metric_name_normalized.\n"
            f"If a metric from this list is not present in the paper, do NOT fabricate it — omit it."
        )
    return "\n".join(parts)


def _get_client() -> AsyncOpenAI:
    c = get_llm_client_config()
    return AsyncOpenAI(
        api_key=c.api_key,
        base_url=c.base_url,
        timeout=120.0,
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
async def _call_llm(paper: Paper, metrics_of_interest: list[str] | None = None) -> dict:
    """Call the LLM and return parsed JSON dict."""
    cfg = get_llm_client_config()
    client = _get_client()
    user_msg = _build_user_prompt(paper, metrics_of_interest=metrics_of_interest)

    response = await client.chat.completions.create(
        model=cfg.model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=4096,
        **get_llm_extra_request_kwargs(),
    )

    raw = response.choices[0].message.content or ""

    # Strip markdown code fences if the model wraps its output
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = lines[1:]  # drop opening ```json or ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)

    return json.loads(raw)


def _default_evidence_snippet(paper: Paper | None) -> str:
    """Non-empty snippet for coerced evidence fields (QualitativeFinding min_length=1)."""
    if paper is not None:
        ab = (paper.abstract or "").strip()
        if len(ab) >= 20:
            return ab[:400]
        t = (paper.title or "").strip()
        if t:
            return t[:400]
    return "Evidence not specified by model."


# Top-level keys allowed on nested ``device`` / ``drug`` objects (models use extra="forbid").
_DEVICE_TOP_KEYS: frozenset[str] = frozenset({
    "product_name",
    "device_category",
    "manufacturer",
    "intended_use",
    "indications",
    "anatomical_site",
    "material",
    "key_features",
    "device_class",
    "energy_source",
    "sterilization_method",
})
_DRUG_TOP_KEYS: frozenset[str] = frozenset({
    "product_name",
    "active_ingredient",
    "drug_class",
    "route",
    "indications",
    "formulation_features",
})


def _collect_strings_from_llm_node(node: object) -> list[str]:
    """Pull human-readable strings from an LLM sub-object (Evidence* or raw)."""
    out: list[str] = []
    if isinstance(node, dict):
        v = node.get("value")
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str) and x.strip():
                    out.append(x.strip())
    return out


def _drop_invalid_evidence_wrapper(block: dict, key: str) -> None:
    """Remove nested dict if it has no usable ``value`` (avoids Pydantic errors)."""
    sub = block.get(key)
    if not isinstance(sub, dict) or "value" not in sub:
        return
    val = sub.get("value")
    if isinstance(val, str):
        if not val.strip():
            block.pop(key, None)
    elif isinstance(val, list):
        if not val:
            block.pop(key, None)
    elif val is None:
        block.pop(key, None)


def _sanitize_device_drug_blocks(data: dict) -> None:
    """Strip unknown keys models reject; map aliases; salvage hints into key_features."""
    dev = data.get("device")
    if isinstance(dev, dict):
        extra_features = (
            _collect_strings_from_llm_node(dev.get("model_number"))
            + _collect_strings_from_llm_node(dev.get("device_type"))
            + _collect_strings_from_llm_node(dev.get("design_features"))
        )
        if "anatomical_location" in dev and "anatomical_site" not in dev:
            dev["anatomical_site"] = dev.pop("anatomical_location")

        for k in list(dev.keys()):
            if k not in _DEVICE_TOP_KEYS:
                dev.pop(k, None)

        if extra_features and "key_features" not in dev:
            dev["key_features"] = {
                "value": extra_features[:20],
                "evidence_snippet": (extra_features[0][:400] if extra_features else "device"),
                "evidence_section": "abstract",
            }

        for fk in (
            "product_name",
            "device_category",
            "manufacturer",
            "intended_use",
            "indications",
            "anatomical_site",
            "material",
            "key_features",
            "energy_source",
            "sterilization_method",
        ):
            _drop_invalid_evidence_wrapper(dev, fk)

    dr = data.get("drug")
    if isinstance(dr, dict):
        for k in list(dr.keys()):
            if k not in _DRUG_TOP_KEYS:
                dr.pop(k, None)
        for fk in (
            "product_name",
            "active_ingredient",
            "drug_class",
            "route",
            "indications",
            "formulation_features",
        ):
            _drop_invalid_evidence_wrapper(dr, fk)


def _coerce_nested_evidence_dict(sub: dict, fallback_snip: str) -> None:
    """Patch EvidenceStr / EvidenceStrList-like dicts with null evidence fields."""
    if "value" not in sub:
        return
    val = sub.get("value")
    has_val = val is not None
    if isinstance(val, str):
        has_val = bool(val.strip())
    elif isinstance(val, list):
        has_val = len(val) > 0
    if not has_val:
        return
    es = sub.get("evidence_snippet")
    if es is None or (isinstance(es, str) and not es.strip()):
        if isinstance(val, str) and val.strip():
            sub["evidence_snippet"] = val.strip()[:400]
        else:
            sub["evidence_snippet"] = fallback_snip[:400]
    sec = sub.get("evidence_section")
    if sec is None or (isinstance(sec, str) and not str(sec).strip()):
        sub["evidence_section"] = "abstract"


def _coerce_llm_output(data: dict, paper: Paper | None = None) -> None:
    """Mutate LLM output in-place to patch common schema deviations."""
    fallback_snip = _default_evidence_snippet(paper)

    _sanitize_device_drug_blocks(data)

    for block_key in ("drug", "device"):
        block = data.get(block_key)
        if not isinstance(block, dict):
            continue
        for sub in block.values():
            if isinstance(sub, dict):
                _coerce_nested_evidence_dict(sub, fallback_snip)

    # qualitative_findings: LLM sometimes sends {"finding": "...", ...} without tag/status
    for qf in data.get("qualitative_findings", []):
        if not isinstance(qf, dict):
            continue
        if "tag" not in qf:
            # Derive tag from 'finding' field if present, else use empty string
            raw_finding = qf.pop("finding", "")
            qf["tag"] = str(raw_finding)[:120] if raw_finding else ""
        if "status" not in qf:
            qf["status"] = "unclear"
        es = qf.get("evidence_snippet")
        if es is None or (isinstance(es, str) and not es.strip()):
            qf["evidence_snippet"] = (qf.get("tag") or "").strip() or fallback_snip
        sec = qf.get("evidence_section")
        if sec is None or (isinstance(sec, str) and not str(sec).strip()):
            qf["evidence_section"] = "unknown"

    # metrics: LLM sometimes omits metric_name_normalized or sends incomplete value types
    for m in data.get("metrics", []):
        if not isinstance(m, dict):
            continue
        if not m.get("metric_name_normalized"):
            m["metric_name_normalized"] = m.get("metric_name_raw") or m.get("metric_category", "unknown_metric")
        # Downgrade incomplete percentage/numeric metrics to text to avoid validation errors
        vt = m.get("value_type")
        if vt in ("percentage", "numeric") and m.get("numeric_value") is None:
            m["value_type"] = "text"
            if not m.get("text_value"):
                m["text_value"] = m.get("metric_name_raw") or m.get("metric_name_normalized", "value not extracted")
        elif vt == "range" and (m.get("value_min") is None or m.get("value_max") is None):
            m["value_type"] = "text"
            if not m.get("text_value"):
                m["text_value"] = m.get("metric_name_raw") or m.get("metric_name_normalized", "range not extracted")
        elif vt == "binary":
            tv = m.get("text_value")
            if tv not in ("yes", "no", "unclear"):
                m["text_value"] = "unclear"
        es_m = m.get("evidence_snippet")
        if es_m is None or (isinstance(es_m, str) and not es_m.strip()):
            label = (m.get("metric_name_raw") or m.get("metric_name_normalized") or "").strip()
            m["evidence_snippet"] = label[:400] if label else fallback_snip[:400]
        sec_m = m.get("evidence_section")
        if sec_m is None or (isinstance(sec_m, str) and not str(sec_m).strip()):
            m["evidence_section"] = "abstract"


async def extract_paper(
    paper: Paper,
    metrics_of_interest: list[str] | None = None,
) -> ExtractionResult:
    """Run LLM extraction on a paper and return a validated ExtractionResult.

    When ``metrics_of_interest`` is supplied, those metric names are injected
    as hints into the prompt so the LLM prioritizes extracting them.

    Injects paper PMID/DOI into the result if the LLM omits them.
    Falls back to a minimal extraction if the LLM output fails validation.
    """
    try:
        data = await _call_llm(paper, metrics_of_interest=metrics_of_interest)
    except json.JSONDecodeError as exc:
        logger.error("LLM returned invalid JSON for PMID={}: {}", paper.pmid, exc)
        return _fallback_extraction(paper, f"LLM returned invalid JSON: {exc}")
    except Exception as exc:
        logger.error("LLM call failed for PMID={}: {}", paper.pmid, exc)
        return _fallback_extraction(paper, f"LLM call failed: {exc}")

    # Inject paper identifiers
    if paper.pmid:
        data.setdefault("pmid", paper.pmid)
    if paper.doi:
        data.setdefault("doi", paper.doi)

    # Drop "regulatory" key if present (not in our Pydantic model)
    data.pop("regulatory", None)

    # Coerce LLM output to match schema before validation
    _coerce_llm_output(data, paper)

    try:
        result = ExtractionResult.model_validate(data)
        logger.info("LLM extraction succeeded for PMID={}", paper.pmid)
        return result
    except Exception as exc:
        logger.warning(
            "LLM output failed Pydantic validation for PMID={}: {}",
            paper.pmid, exc,
        )
        return _fallback_extraction(paper, f"Validation failed: {exc}")


def _fallback_extraction(paper: Paper, warning: str) -> ExtractionResult:
    """Minimal valid ExtractionResult when LLM extraction fails."""
    snippet = (paper.title or "")[:100] or "untitled"
    return ExtractionResult(
        pmid=paper.pmid,
        doi=paper.doi,
        paper_synopsis={
            "value": f"Extraction failed for this paper. {warning[:200]}",
            "supporting_evidence_snippets": [snippet],
        },
        topical_relevance={
            "label": "low",
            "evidence_snippet": snippet,
            "evidence_section": "title",
        },
        study={
            "study_type": {
                "value": "unknown",
                "evidence_snippet": snippet,
                "evidence_section": "title",
            },
            "evidence_domain": {
                "value": "unknown",
                "evidence_snippet": snippet,
                "evidence_section": "title",
            },
        },
        extraction_warnings=[warning],
    )
