"""Multi-source pool fetcher: fan out to every configured database in parallel.

Each source returns up to ``pool_size`` results, all converted to the unified
:class:`~app.models.paper.Paper` model.  The caller (search API) passes the
combined pool into triage which trims to ``max_results``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from loguru import logger

from app.clients.accessgudid import AccessGUDIDClient
from app.clients.clinicaltrials import ClinicalTrialsClient
from app.clients.dailymed import DailyMedClient
from app.clients.openfda import OpenFDAClient
from app.core.config import settings
from app.models.paper import Paper
from app.models.search import TargetProductProfile
from app.services.pubmed import build_pubmed_query, search_pubmed


# ---------------------------------------------------------------------------
# Per-source converters  (raw API dict -> Paper)
# ---------------------------------------------------------------------------

def _trial_to_paper(study: dict[str, Any]) -> Paper | None:
    proto = study.get("protocolSection", study)
    ident = proto.get("identificationModule", {})
    nct = ident.get("nctId", "")
    if not nct:
        return None

    desc = proto.get("descriptionModule", {})
    cond = proto.get("conditionsModule", {})
    status_mod = proto.get("statusModule", {})

    brief = desc.get("briefSummary", "")
    detailed = desc.get("detailedDescription", "")
    abstract = brief or detailed or None

    conditions = cond.get("conditions", [])
    keywords_raw = cond.get("keywords", [])

    pub_date: date | None = None
    start_str = status_mod.get("startDateStruct", {}).get("date", "")
    if start_str:
        try:
            parts = start_str.split("-")
            pub_date = date(int(parts[0]), int(parts[1]) if len(parts) > 1 else 1, 1)
        except (ValueError, IndexError):
            pass

    return Paper(
        identifier=nct,
        source="ClinicalTrials",
        title=ident.get("briefTitle") or ident.get("officialTitle") or nct,
        abstract=abstract,
        keywords=conditions + keywords_raw,
        published_date=pub_date,
        source_url=f"https://clinicaltrials.gov/study/{nct}",
    )


def _510k_to_paper(rec: dict[str, Any]) -> Paper | None:
    k = rec.get("k_number", "")
    if not k:
        return None

    device_name = rec.get("device_name", "")
    applicant = rec.get("applicant", "")
    statement = rec.get("statement_or_summary", "") or ""

    pub_date: date | None = None
    dec = rec.get("decision_date", "")
    if dec:
        try:
            parts = dec.split("/")
            if len(parts) == 3:
                pub_date = date(int(parts[2]), int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass

    return Paper(
        identifier=k,
        source="openFDA",
        title=f"510(k) {k}: {device_name}" if device_name else f"510(k) {k}",
        abstract=statement[:3000] if statement else None,
        authors=[applicant] if applicant else [],
        published_date=pub_date,
        source_url=f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k}",
    )


def _drug_label_to_paper(rec: dict[str, Any]) -> Paper | None:
    openfda = rec.get("openfda", {})
    brand_list = openfda.get("brand_name") or []
    brand = brand_list[0] if brand_list else ""
    app_nums = openfda.get("application_number") or []
    app_num = app_nums[0] if app_nums else ""
    if not brand and not app_num:
        return None

    identifier = app_num or brand
    iu = rec.get("indications_and_usage") or []
    abstract = iu[0][:3000] if iu else None

    generic_list = openfda.get("generic_name") or []
    mfr_list = openfda.get("manufacturer_name") or []

    return Paper(
        identifier=f"FDA_LABEL:{identifier}",
        source="openFDA",
        title=f"{brand} ({generic_list[0]})" if generic_list else brand or identifier,
        abstract=abstract,
        authors=mfr_list[:3],
        source_url=f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query={brand}" if brand else None,
    )


def _dailymed_to_paper(item: dict[str, Any]) -> Paper | None:
    setid = item.get("setid", "")
    if not setid:
        return None
    drug_name = item.get("drug_name") or item.get("title", "")
    return Paper(
        identifier=f"DM:{setid}",
        source="DailyMed",
        title=drug_name or f"DailyMed {setid}",
        source_url=f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}",
    )


def _gudid_to_paper(result: dict[str, Any]) -> Paper | None:
    device = result.get("device") or result if isinstance(result, dict) else {}
    di = device.get("deviceIdentifier", device.get("di", ""))
    if not di:
        return None
    brand = device.get("brandName", "")
    company = device.get("companyName", "")
    desc = device.get("deviceDescription", "") or ""
    return Paper(
        identifier=f"GUDID:{di}",
        source="AccessGUDID",
        title=brand or f"GUDID {di}",
        abstract=desc[:3000] if desc else None,
        authors=[company] if company else [],
        source_url=f"https://accessgudid.nlm.nih.gov/devices/{di}",
    )


# ---------------------------------------------------------------------------
# Safe coroutine wrapper
# ---------------------------------------------------------------------------

async def _safe(coro: Any, label: str) -> list[Any]:
    try:
        result = await coro
        return result if isinstance(result, list) else []
    except Exception as exc:
        logger.warning("Pool fetch [{}] failed: {}", label, exc)
        return []


# ---------------------------------------------------------------------------
# Query builders per source
# ---------------------------------------------------------------------------

def _build_query_term(
    query: str,
    target: TargetProductProfile | None,
) -> str:
    """Best free-text query for non-PubMed sources."""
    if target:
        anchor = (target.active_ingredient or target.product_name or "").strip()
        if anchor:
            inds = " ".join(i.replace("_", " ") for i in target.indications[:2])
            return f"{anchor} {inds}".strip()
    return query.strip()


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PoolResult:
    """Aggregated pool with per-source counts."""
    papers: list[Paper] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def search_all_sources(
    query: str,
    target_product: TargetProductProfile | None,
    pool_size: int,
    *,
    keywords: list[str] | None = None,
    min_year: int | None = None,
    max_year: int | None = None,
    country: str | None = None,
) -> PoolResult:
    """Fan out to every database and return a unified, deduplicated paper pool.

    Each database returns up to *pool_size* results.  The caller is expected
    to pass the combined pool through triage to trim to ``max_results``.
    """
    free_text = _build_query_term(query, target_product)

    # --- Build PubMed query (structured, uses target profile) ---
    pubmed_term = build_pubmed_query(query, target_product, keywords or None)

    # --- Instantiate clients ---
    openfda = OpenFDAClient(settings)
    ct = ClinicalTrialsClient(settings)
    dm = DailyMedClient(settings)
    gudid = AccessGUDIDClient(settings)

    # --- ClinicalTrials query construction ---
    ct_condition = None
    ct_intervention = None
    if target_product:
        ct_condition = " ".join(
            i.replace("_", " ") for i in target_product.indications[:2]
        ) or None
        ct_intervention = (
            target_product.product_name
            or target_product.active_ingredient
            or None
        )

    # --- Fan out in parallel ---
    tasks = [
        _safe(search_pubmed(pubmed_term, max_results=pool_size, min_year=min_year, max_year=max_year, country=country), "PubMed"),
        _safe(openfda.search_device(free_text, limit=pool_size), "openFDA_device"),
        _safe(openfda.search_drug_label(free_text, limit=pool_size), "openFDA_drug"),
        _safe(ct.search_studies(
            query=free_text if not (ct_condition or ct_intervention) else None,
            condition=ct_condition,
            intervention=ct_intervention,
            limit=pool_size,
        ), "ClinicalTrials"),
        _safe(dm.search_spls(
            target_product.active_ingredient or target_product.product_name or free_text
            if target_product else free_text,
            limit=pool_size,
        ), "DailyMed"),
        _safe(gudid.search_devices(
            brand_name=target_product.product_name or free_text if target_product else free_text,
        ), "AccessGUDID"),
    ]

    (
        pubmed_papers,
        openfda_devices,
        openfda_drugs,
        ct_studies,
        dm_results,
        gudid_results,
    ) = await asyncio.gather(*tasks)

    # --- Convert and collect ---
    all_papers: list[Paper] = []
    counts: dict[str, int] = {}

    # PubMed (already Paper objects)
    for p in pubmed_papers:
        if isinstance(p, Paper):
            if not p.identifier:
                p.identifier = p.pmid
            all_papers.append(p)
    counts["PubMed"] = len([p for p in pubmed_papers if isinstance(p, Paper)])

    n = 0
    for rec in openfda_devices:
        paper = _510k_to_paper(rec)
        if paper:
            all_papers.append(paper)
            n += 1
    counts["openFDA_device"] = n

    n = 0
    for rec in openfda_drugs:
        paper = _drug_label_to_paper(rec)
        if paper:
            all_papers.append(paper)
            n += 1
    counts["openFDA_drug"] = n

    n = 0
    for study in ct_studies:
        paper = _trial_to_paper(study)
        if paper:
            all_papers.append(paper)
            n += 1
    counts["ClinicalTrials"] = n

    n = 0
    for item in dm_results:
        paper = _dailymed_to_paper(item)
        if paper:
            all_papers.append(paper)
            n += 1
    counts["DailyMed"] = n

    n = 0
    for item in gudid_results:
        paper = _gudid_to_paper(item)
        if paper:
            all_papers.append(paper)
            n += 1
    counts["AccessGUDID"] = n

    # --- Deduplicate by uid ---
    seen: set[str] = set()
    deduped: list[Paper] = []
    for p in all_papers:
        key = p.uid
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    logger.info(
        "Pool: {} total ({} deduped) from {} sources: {}",
        len(all_papers),
        len(deduped),
        len([v for v in counts.values() if v > 0]),
        counts,
    )

    return PoolResult(papers=deduped, source_counts=counts)
