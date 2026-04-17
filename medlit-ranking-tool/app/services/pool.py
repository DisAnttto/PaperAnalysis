"""Multi-source pool fetcher: fan out to every configured database in parallel.

Each source returns up to ``pool_size`` results, all converted to the unified
:class:`~app.models.paper.Paper` model.  The caller (search API) passes the
combined pool into triage which trims to ``max_results``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
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


# Human-readable labels for streaming UI / logs
_SOURCE_DISPLAY = {
    "PubMed": "PubMed",
    "OpenAlex": "OpenAlex",
    "openFDA_device": "openFDA (device)",
    "openFDA_drug": "openFDA (drug)",
    "ClinicalTrials": "ClinicalTrials.gov",
    "DailyMed": "DailyMed",
    "AccessGUDID": "AccessGUDID",
    "PubMed_supplementary": "PubMed (supplementary)",
}


def _display_source(label: str) -> str:
    return _SOURCE_DISPLAY.get(label, label)


def _convert_raw_to_papers(label: str, raw: list[Any]) -> list[Paper]:
    """Turn a raw per-source API list into ``Paper`` objects (same as ``search_all_sources``)."""
    if label == "PubMed" or label == "PubMed_supplementary":
        out: list[Paper] = []
        for p in raw:
            if isinstance(p, Paper):
                if not p.identifier:
                    p.identifier = p.pmid
                out.append(p)
        return out
    if label == "OpenAlex":
        out = []
        for work in raw:
            paper = _openalex_to_paper(work)
            if paper:
                out.append(paper)
        return out
    if label == "openFDA_device":
        out = []
        for rec in raw:
            paper = _510k_to_paper(rec)
            if paper:
                out.append(paper)
        return out
    if label == "openFDA_drug":
        out = []
        for rec in raw:
            paper = _drug_label_to_paper(rec)
            if paper:
                out.append(paper)
        return out
    if label == "ClinicalTrials":
        out = []
        for study in raw:
            paper = _trial_to_paper(study)
            if paper:
                out.append(paper)
        return out
    if label == "DailyMed":
        out = []
        for item in raw:
            paper = _dailymed_to_paper(item)
            if paper:
                out.append(paper)
        return out
    if label == "AccessGUDID":
        out = []
        for item in raw:
            paper = _gudid_to_paper(item)
            if paper:
                out.append(paper)
        return out
    return []


def _dedupe_new_batch(
    batch: list[Paper],
    seen_uids: set[str],
    seen_dois: set[str],
) -> list[Paper]:
    """Append-only global dedup: return papers in *batch* not yet in *seen_* sets."""
    new: list[Paper] = []
    for p in batch:
        key = p.uid
        doi_key = (p.doi or "").strip().lower()
        if key in seen_uids:
            continue
        if doi_key and doi_key in seen_dois:
            continue
        seen_uids.add(key)
        if doi_key:
            seen_dois.add(doi_key)
        new.append(p)
    return new


async def _timed_await(label: str, coro: Any) -> tuple[str, list[Any], float]:
    """Await one source fetch and return (label, raw_list, duration_ms)."""
    t0 = time.perf_counter()
    try:
        raw = await coro
    except Exception as exc:
        logger.warning("Pool fetch [{}] failed: {}", label, exc)
        raw = []
    data = raw if isinstance(raw, list) else []
    dt_ms = (time.perf_counter() - t0) * 1000.0
    return label, data, dt_ms


async def iter_pool_sources(
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
) -> AsyncIterator[tuple[str, list[Paper], float]]:
    """Yield ``(source_key, papers, duration_ms)`` as each database finishes.

    Parallel sources complete in completion order (not fixed order).  Papers are
    converted to :class:`Paper`.  Global deduplication is applied by
    :func:`search_all_sources` or the streaming search handler.  Supplementary
    PubMed runs after all parallel sources and is yielded as
    ``PubMed_supplementary`` when non-empty.
    """
    _enabled = enabled_sources or frozenset({
        "PubMed", "OpenAlex", "openFDA_device", "openFDA_drug",
        "ClinicalTrials", "DailyMed", "AccessGUDID",
    })
    _budgets = budget_overrides or {}

    def _budget(source_name: str) -> int:
        return _budgets.get(source_name, pool_size)

    free_text = _build_query_term(query, target_product)
    pubmed_term = build_pubmed_query(query, target_product, keywords or None)

    openfda = OpenFDAClient(settings)
    ct = ClinicalTrialsClient(settings)
    dm = DailyMedClient(settings)
    gudid = AccessGUDIDClient(settings)
    oalex = OpenAlexClient(settings)

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

    async def _noop() -> list[Any]:
        return []

    pending: set[asyncio.Task] = set()

    def _add(label: str, coro: Any) -> None:
        pending.add(asyncio.create_task(_timed_await(label, coro)))

    if "PubMed" in _enabled:
        _add(
            "PubMed",
            _safe(
                search_pubmed(
                    pubmed_term,
                    max_results=_budget("PubMed"),
                    min_year=min_year,
                    max_year=max_year,
                    country=country,
                    target=target_product,
                    free_text_fallback=free_text,
                ),
                "PubMed",
            ),
        )
    if "OpenAlex" in _enabled:
        _add("OpenAlex", _safe(oalex.search_works(free_text, limit=_budget("OpenAlex")), "OpenAlex"))
    if "openFDA_device" in _enabled:
        _add(
            "openFDA_device",
            _safe(openfda.search_device(free_text, limit=_budget("openFDA_device")), "openFDA_device"),
        )
    if "openFDA_drug" in _enabled:
        _add(
            "openFDA_drug",
            _safe(openfda.search_drug_label(free_text, limit=_budget("openFDA_drug")), "openFDA_drug"),
        )
    if "ClinicalTrials" in _enabled:
        _add(
            "ClinicalTrials",
            _safe(
                ct.search_studies(
                    query=free_text if not (ct_condition or ct_intervention) else None,
                    condition=ct_condition,
                    intervention=ct_intervention,
                    limit=_budget("ClinicalTrials"),
                ),
                "ClinicalTrials",
            ),
        )
    if "DailyMed" in _enabled:
        _add(
            "DailyMed",
            _safe(
                dm.search_spls(
                    target_product.active_ingredient or target_product.product_name or free_text
                    if target_product else free_text,
                    limit=_budget("DailyMed"),
                ),
                "DailyMed",
            ),
        )
    if "AccessGUDID" in _enabled:
        _add(
            "AccessGUDID",
            _safe(
                gudid.search_devices(
                    brand_name=target_product.product_name or free_text if target_product else free_text,
                ),
                "AccessGUDID",
            ),
        )

    primary_pmids: set[str] = set()
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            label, raw, dt_ms = task.result()
            papers = _convert_raw_to_papers(label, raw)
            if label == "PubMed":
                primary_pmids = {p.uid for p in papers if p.uid}
            yield label, papers, dt_ms

    if "PubMed" in _enabled and keywords:
        t0 = time.perf_counter()
        supp = await _supplementary_pubmed(
            query,
            target_product,
            keywords,
            max_results=_budget("PubMed"),
            min_year=min_year,
            max_year=max_year,
            country=country,
            primary_pmids=primary_pmids,
        )
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if supp:
            yield "PubMed_supplementary", supp, dt_ms


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

    Uses :func:`iter_pool_sources` internally (same completion-order dedup as the
    streaming search UI).
    """
    seen_uids: set[str] = set()
    seen_dois: set[str] = set()
    all_papers: list[Paper] = []
    counts: dict[str, int] = {}
    raw_total = 0

    async for label, batch, _dt in iter_pool_sources(
        query,
        target_product,
        pool_size,
        keywords=keywords,
        min_year=min_year,
        max_year=max_year,
        country=country,
        enabled_sources=enabled_sources,
        budget_overrides=budget_overrides,
    ):
        raw_total += len(batch)
        ck = "PubMed" if label == "PubMed_supplementary" else label
        counts[ck] = counts.get(ck, 0) + len(batch)
        new_batch = _dedupe_new_batch(batch, seen_uids, seen_dois)
        all_papers.extend(new_batch)

    logger.info(
        "Pool: {} raw rows ({} deduped) from {} sources: {}",
        raw_total,
        len(all_papers),
        len([v for v in counts.values() if v > 0]),
        counts,
    )

    return PoolResult(papers=all_papers, source_counts=counts)
