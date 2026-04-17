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
from app.clients.openalex import OpenAlexClient
from app.clients.openfda import OpenFDAClient
from app.core.config import settings
from app.models.paper import Paper
from app.models.search import TargetProductProfile
from app.services.pubmed import (
    build_pubmed_query,
    search_pubmed,
    search_pmids,
    fetch_papers,
)


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


def _openalex_to_paper(work: dict[str, Any]) -> Paper | None:
    """Convert an OpenAlex work object to a Paper."""
    title = work.get("title") or ""
    if not title:
        return None
    doi = work.get("doi") or ""
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]

    ids = work.get("ids", {})
    pmid = (ids.get("pmid") or "").replace("https://pubmed.ncbi.nlm.nih.gov/", "").strip("/")

    authorship_list = work.get("authorships", [])
    authors = []
    for a in authorship_list[:20]:
        name = a.get("author", {}).get("display_name", "")
        if name:
            authors.append(name)

    abstract_text = None
    inv_index = work.get("abstract_inverted_index")
    if inv_index and isinstance(inv_index, dict):
        positions: list[tuple[int, str]] = []
        for word, idxs in inv_index.items():
            for idx in idxs:
                positions.append((idx, word))
        positions.sort()
        abstract_text = " ".join(w for _, w in positions)

    pub_date = None
    pd_str = work.get("publication_date") or ""
    if pd_str:
        try:
            pub_date = date.fromisoformat(pd_str)
        except ValueError:
            pass

    journal_name = None
    primary_loc = work.get("primary_location", {}) or {}
    source_info = primary_loc.get("source", {}) or {}
    journal_name = source_info.get("display_name")

    concepts = work.get("concepts", [])
    kw = [c.get("display_name", "") for c in concepts[:10] if c.get("display_name")]

    openalex_id = work.get("id", "")

    return Paper(
        pmid=pmid or None,
        doi=doi or None,
        identifier=openalex_id or None,
        source="OpenAlex",
        title=title,
        abstract=abstract_text,
        authors=authors,
        journal=journal_name,
        published_date=pub_date,
        keywords=kw,
        source_url=openalex_id or None,
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


async def _supplementary_pubmed(
    query: str,
    target_product: TargetProductProfile | None,
    keywords: list[str] | None,
    max_results: int,
    min_year: int | None,
    max_year: int | None,
    country: str | None,
    primary_pmids: set[str],
) -> list[Paper]:
    """Run complementary PubMed queries to broaden recall.

    The primary PubMed query is built from anchor + indications + keywords, which
    retrieves device/product-focused papers. But many important clinical papers
    (e.g. "intraocular pressure after cataract surgery") don't mention the device
    name. This function fires additional focused queries and returns papers not
    already found by the primary search.
    """
    procedure_terms: list[str] = []
    if target_product:
        for ind in target_product.indications:
            s = ind.strip().replace("_", " ")
            if s:
                procedure_terms.append(s)

    if not procedure_terms:
        return []

    proc_or = " OR ".join(
        f'"{p}"[Title/Abstract]' if " " in p else f'{p}[Title/Abstract]'
        for p in procedure_terms[:4]
    )

    metric_seeds: list[str] = []
    for kw in keywords or []:
        low = kw.lower()
        if any(t in low for t in ("iop", "intraocular pressure", "ocular hypertension",
                                   "pressure", "bcva", "visual acuity")):
            metric_seeds.append(kw)

    query_low = query.lower()
    if "intraocular pressure" in query_low and not any("intraocular pressure" in s.lower() for s in metric_seeds):
        metric_seeds.insert(0, "intraocular pressure")
    if "iop" in query_low.split() and not any(s.lower() == "iop" for s in metric_seeds):
        metric_seeds.insert(0, "IOP")

    extra_queries: list[str] = []
    for mt in metric_seeds:
        mt_clean = mt.strip()
        words = mt_clean.split()
        if len(words) > 3:
            mt_clean = " ".join(words[:3])
        if " " in mt_clean:
            mt_tag = f'"{mt_clean}"[Title/Abstract]'
        else:
            mt_tag = f'{mt_clean}[Title/Abstract]'
        extra_queries.append(f'{mt_tag} AND ({proc_or})')

    if "postoperative" in query_low:
        for base in ["intraocular pressure", "IOP"]:
            eq = f'"{base}"[Title/Abstract] AND postoperative[Title/Abstract]'
            if eq not in extra_queries:
                extra_queries.append(eq)

    for kw in keywords or []:
        low = kw.lower()
        if any(t in low for t in ("viscoelastic", "pseudoexfoliation", "glaucoma")):
            if " " in kw:
                kw_tag = f'"{kw}"[Title/Abstract]'
            else:
                kw_tag = f'{kw}[Title/Abstract]'
            base = '"intraocular pressure"[Title/Abstract]'
            eq = f'{base} AND {kw_tag}'
            if eq not in extra_queries:
                extra_queries.append(eq)

    has_day_terms = any(t in query_low for t in ("day 1", "first day", "postoperative day"))
    if has_day_terms and proc_or:
        eq = (
            '"intraocular pressure"[Title/Abstract] AND '
            '("day 1"[Title/Abstract] OR "first postoperative"[Title/Abstract] '
            'OR "early postoperative"[Title/Abstract]) AND '
            f'({proc_or})'
        )
        if eq not in extra_queries:
            extra_queries.append(eq)

    if not extra_queries:
        return []

    seen = set(primary_pmids)
    new_papers: list[Paper] = []

    for eq in extra_queries[:8]:
        try:
            pmids = await search_pmids(
                eq, max_results=max_results,
                min_year=min_year, max_year=max_year, country=country,
            )
            novel = [p for p in pmids if p not in seen][:50]
            if novel:
                papers = await fetch_papers(novel)
                for pp in papers:
                    if pp.uid and pp.uid not in seen:
                        pp.source = "PubMed"
                        new_papers.append(pp)
                        seen.add(pp.uid)
                logger.info(
                    "Supplementary PubMed query {!r} added {} new papers",
                    eq[:80], len(novel),
                )
        except Exception as exc:
            logger.warning("Supplementary PubMed query failed: {}", exc)

    return new_papers


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
    enabled_sources: frozenset[str] | None = None,
    budget_overrides: dict[str, int] | None = None,
) -> PoolResult:
    """Fan out to every database and return a unified, deduplicated paper pool.

    Each database returns up to *pool_size* results (or the budget override).
    When *enabled_sources* is provided, only those sources are queried.
    The caller is expected to pass the combined pool through triage to trim
    to ``max_results``.
    """
    _enabled = enabled_sources or frozenset({
        "PubMed", "OpenAlex", "openFDA_device", "openFDA_drug",
        "ClinicalTrials", "DailyMed", "AccessGUDID",
    })
    _budgets = budget_overrides or {}

    def _budget(source_name: str) -> int:
        return _budgets.get(source_name, pool_size)

    free_text = _build_query_term(query, target_product)

    # --- Build PubMed query (structured, uses target profile) ---
    pubmed_term = build_pubmed_query(query, target_product, keywords or None)

    # --- Instantiate clients ---
    openfda = OpenFDAClient(settings)
    ct = ClinicalTrialsClient(settings)
    dm = DailyMedClient(settings)
    gudid = AccessGUDIDClient(settings)
    oalex = OpenAlexClient(settings)

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

    # --- Fan out in parallel (only enabled sources) ---
    async def _noop() -> list:
        return []

    tasks = [
        _safe(search_pubmed(
            pubmed_term,
            max_results=_budget("PubMed"),
            min_year=min_year,
            max_year=max_year,
            country=country,
            target=target_product,
            free_text_fallback=free_text,
        ), "PubMed")
        if "PubMed" in _enabled else _noop(),

        _safe(oalex.search_works(free_text, limit=_budget("OpenAlex")), "OpenAlex")
        if "OpenAlex" in _enabled else _noop(),

        _safe(openfda.search_device(free_text, limit=_budget("openFDA_device")), "openFDA_device")
        if "openFDA_device" in _enabled else _noop(),

        _safe(openfda.search_drug_label(free_text, limit=_budget("openFDA_drug")), "openFDA_drug")
        if "openFDA_drug" in _enabled else _noop(),

        _safe(ct.search_studies(
            query=free_text if not (ct_condition or ct_intervention) else None,
            condition=ct_condition,
            intervention=ct_intervention,
            limit=_budget("ClinicalTrials"),
        ), "ClinicalTrials")
        if "ClinicalTrials" in _enabled else _noop(),

        _safe(dm.search_spls(
            target_product.active_ingredient or target_product.product_name or free_text
            if target_product else free_text,
            limit=_budget("DailyMed"),
        ), "DailyMed")
        if "DailyMed" in _enabled else _noop(),

        _safe(gudid.search_devices(
            brand_name=target_product.product_name or free_text if target_product else free_text,
        ), "AccessGUDID")
        if "AccessGUDID" in _enabled else _noop(),
    ]

    (
        pubmed_papers,
        oalex_works,
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
    for work in oalex_works:
        paper = _openalex_to_paper(work)
        if paper:
            all_papers.append(paper)
            n += 1
    counts["OpenAlex"] = n

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

    # --- Supplementary PubMed queries for metric-focused recall ---
    if "PubMed" in _enabled and keywords:
        primary_pmids = {p.uid for p in all_papers if p.uid}
        supp_papers = await _supplementary_pubmed(
            query, target_product, keywords,
            max_results=_budget("PubMed"),
            min_year=min_year, max_year=max_year, country=country,
            primary_pmids=primary_pmids,
        )
        if supp_papers:
            all_papers.extend(supp_papers)
            counts["PubMed"] = counts.get("PubMed", 0) + len(supp_papers)

    # --- Deduplicate by uid + DOI ---
    # First-occurrence wins.  A paper is a duplicate if its uid OR its
    # normalised DOI was already seen.
    seen_uids: set[str] = set()
    seen_dois: set[str] = set()
    deduped: list[Paper] = []
    for p in all_papers:
        key = p.uid
        doi_key = (p.doi or "").strip().lower()
        if key in seen_uids:
            continue
        if doi_key and doi_key in seen_dois:
            continue
        seen_uids.add(key)
        if doi_key:
            seen_dois.add(doi_key)
        deduped.append(p)

    logger.info(
        "Pool: {} total ({} deduped) from {} sources: {}",
        len(all_papers),
        len(deduped),
        len([v for v in counts.values() if v > 0]),
        counts,
    )

    return PoolResult(papers=deduped, source_counts=counts)
