"""Query rewrite generator: produce parallel search variants per source.

Given a user query and target product profile, this module generates multiple
query rewrites optimised for each data source's query language:

  PubMed        — structured boolean with field tags ([Title/Abstract], MeSH)
  ClinicalTrials — condition + intervention pairs
  openFDA       — free-text product/device terms
  DailyMed      — ingredient/product name
  AccessGUDID   — brand name / device description

The pool fetcher can run all rewrites in parallel and merge results, improving
recall without sacrificing precision (triage handles that).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.search import TargetProductProfile


@dataclass
class QueryRewrite:
    """A single query variant for a specific source."""

    source: str
    query_text: str
    variant: str = "primary"
    reasoning: str = ""


@dataclass
class RewriteSet:
    """All query rewrites for one search request."""

    pubmed: list[QueryRewrite] = field(default_factory=list)
    openfda_device: list[QueryRewrite] = field(default_factory=list)
    openfda_drug: list[QueryRewrite] = field(default_factory=list)
    clinical_trials: list[QueryRewrite] = field(default_factory=list)
    dailymed: list[QueryRewrite] = field(default_factory=list)
    access_gudid: list[QueryRewrite] = field(default_factory=list)


_SYNONYM_TABLE: dict[str, list[str]] = {
    "iop": ["intraocular pressure", "IOP"],
    "intraocular pressure": ["IOP", "intraocular pressure"],
    "bcva": ["best corrected visual acuity", "BCVA", "visual acuity"],
    "visual acuity": ["BCVA", "best corrected visual acuity"],
    "namd": ["neovascular age-related macular degeneration", "nAMD", "wet AMD"],
    "wet amd": ["neovascular age-related macular degeneration", "nAMD", "wet AMD"],
    "dme": ["diabetic macular edema", "DME", "diabetic macular oedema"],
    "diabetic macular edema": ["DME", "diabetic macular edema"],
    "oct": ["optical coherence tomography", "OCT"],
    "cst": ["central subfield thickness", "CST", "central retinal thickness"],
    "iol": ["intraocular lens", "IOL"],
    "intraocular lens": ["IOL", "intraocular lens"],
    "phaco": ["phacoemulsification", "phaco"],
    "phacoemulsification": ["phaco", "phacoemulsification"],
    "ecg": ["electrocardiogram", "ECG", "EKG"],
    "af": ["atrial fibrillation", "AF", "AFib"],
    "atrial fibrillation": ["AF", "AFib", "atrial fibrillation"],
}


def _expand_synonyms(term: str) -> list[str]:
    """Return known synonyms for a term (case-insensitive lookup)."""
    key = term.strip().lower()
    return _SYNONYM_TABLE.get(key, [term])


def _make_boolean_or(terms: list[str]) -> str:
    """Join terms with OR, quoting multi-word phrases."""
    parts = []
    for t in terms:
        if " " in t:
            parts.append(f'"{t}"')
        else:
            parts.append(t)
    return " OR ".join(parts)


def generate_rewrites(
    query: str,
    target_product: TargetProductProfile | None = None,
) -> RewriteSet:
    """Generate parallel query rewrites for each data source."""
    result = RewriteSet()

    anchor = ""
    indications: list[str] = []
    device_cat = ""
    if target_product:
        anchor = (target_product.active_ingredient or target_product.product_name or "").strip()
        indications = [i.replace("_", " ") for i in target_product.indications if i]
        device_cat = (target_product.device_category or "").replace("_", " ").strip()

    # -- PubMed rewrites --
    # Primary: exact passthrough (the existing build_pubmed_query handles this)
    result.pubmed.append(QueryRewrite(
        source="PubMed", query_text=query, variant="primary",
        reasoning="User query passed to build_pubmed_query for structured expansion.",
    ))
    # Synonym expansion rewrite
    for token in query.split():
        syns = _expand_synonyms(token)
        if len(syns) > 1 and syns != [token]:
            expanded = query
            or_clause = f"({_make_boolean_or(syns)})"
            expanded = expanded.replace(token, or_clause, 1)
            result.pubmed.append(QueryRewrite(
                source="PubMed", query_text=expanded, variant="synonym_expanded",
                reasoning=f"Expanded '{token}' to synonyms: {syns}",
            ))
            break  # one synonym expansion per query

    # -- openFDA device rewrites --
    if anchor:
        result.openfda_device.append(QueryRewrite(
            source="openFDA_device", query_text=anchor, variant="product_name",
        ))
    if device_cat:
        result.openfda_device.append(QueryRewrite(
            source="openFDA_device", query_text=device_cat, variant="device_category",
        ))
    if not result.openfda_device:
        result.openfda_device.append(QueryRewrite(
            source="openFDA_device", query_text=query, variant="free_text",
        ))

    # -- openFDA drug rewrites --
    if anchor:
        result.openfda_drug.append(QueryRewrite(
            source="openFDA_drug", query_text=anchor, variant="ingredient",
        ))
    if not result.openfda_drug:
        result.openfda_drug.append(QueryRewrite(
            source="openFDA_drug", query_text=query, variant="free_text",
        ))

    # -- ClinicalTrials rewrites --
    if indications and anchor:
        result.clinical_trials.append(QueryRewrite(
            source="ClinicalTrials",
            query_text=f"{anchor} {' '.join(indications[:2])}",
            variant="structured",
        ))
    result.clinical_trials.append(QueryRewrite(
        source="ClinicalTrials", query_text=query, variant="free_text",
    ))

    # -- DailyMed rewrites --
    if anchor:
        result.dailymed.append(QueryRewrite(
            source="DailyMed", query_text=anchor, variant="ingredient",
        ))
    if not result.dailymed:
        result.dailymed.append(QueryRewrite(
            source="DailyMed", query_text=query, variant="free_text",
        ))

    # -- AccessGUDID rewrites --
    if target_product and target_product.product_name:
        result.access_gudid.append(QueryRewrite(
            source="AccessGUDID",
            query_text=target_product.product_name,
            variant="brand_name",
        ))
    if device_cat:
        result.access_gudid.append(QueryRewrite(
            source="AccessGUDID", query_text=device_cat, variant="device_category",
        ))
    if not result.access_gudid:
        result.access_gudid.append(QueryRewrite(
            source="AccessGUDID", query_text=query, variant="free_text",
        ))

    return result
