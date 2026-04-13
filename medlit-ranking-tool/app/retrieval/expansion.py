"""Candidate expansion: fan out from a seed record to gather evidence candidates."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from loguru import logger

from app.retrieval.enums import SourceType
from app.retrieval.models import EvidenceRecord, ExtractedTargetProfile, SeedRecord

# ---------------------------------------------------------------------------
# Identifier prefix → source type routing
# ---------------------------------------------------------------------------

_PREFIX_RE = re.compile(
    r"^(?P<prefix>PMID|PMC|NCT|K|DEN|PMA|NDA|BLA|SSED|MAUDE|RECALL)[:_]?",
    re.IGNORECASE,
)


def _classify_seed(identifier: str) -> str:
    """Return a short source-type label from the seed identifier prefix."""
    m = _PREFIX_RE.match(identifier.strip())
    prefix = m.group("prefix").upper() if m else ""
    mapping = {
        "PMID": "pubmed",
        "PMC": "pubmed",
        "NCT": "trial",
        "K": "510k",
        "DEN": "denovo",
        "PMA": "pma",
        "NDA": "drug",
        "BLA": "drug",
    }
    return mapping.get(prefix, "unknown")


# ---------------------------------------------------------------------------
# Per-source converters
# ---------------------------------------------------------------------------

def _pubmed_to_evidence(paper_dict: dict[str, Any]) -> EvidenceRecord | None:
    """Convert a Paper-like dict (from pubmed search) to EvidenceRecord."""
    pmid = paper_dict.get("pmid") or paper_dict.get("id", "")
    if not pmid:
        return None
    return EvidenceRecord(
        identifier=f"PMID:{pmid}",
        source_type=SourceType.pubmed_paper,
        source_name="PubMed",
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        title=paper_dict.get("title"),
        raw_payload=paper_dict,
    )


def _510k_to_evidence(result: dict[str, Any]) -> EvidenceRecord | None:
    k = result.get("k_number", "")
    if not k:
        return None
    return EvidenceRecord(
        identifier=f"510K:{k}",
        source_type=SourceType.fda_510k,
        source_name="FDA 510(k)",
        url=f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k}",
        title=result.get("device_name"),
        product_name=result.get("device_name"),
        manufacturer=result.get("applicant"),
        indication=_split_text(result.get("device_name", "")),
        raw_payload=result,
    )


def _drug_label_to_evidence(result: dict[str, Any]) -> EvidenceRecord | None:
    openfda = result.get("openfda", {})
    brand = (openfda.get("brand_name") or [""])[0]
    nda = (openfda.get("application_number") or [""])[0]
    if not nda and not brand:
        return None
    identifier = f"FDA_LABEL:{nda}" if nda else f"FDA_LABEL:{brand}"
    return EvidenceRecord(
        identifier=identifier,
        source_type=SourceType.fda_label,
        source_name="FDA Drug Label",
        title=brand or nda,
        product_name=brand,
        manufacturer=(openfda.get("manufacturer_name") or [""])[0],
        indication=_split_text((result.get("indications_and_usage") or [""])[0]),
        raw_payload=result,
    )


def _trial_to_evidence(study: dict[str, Any]) -> EvidenceRecord | None:
    proto = study.get("protocolSection", study)
    ident_mod = proto.get("identificationModule", {})
    nct = ident_mod.get("nctId", "")
    if not nct:
        return None
    desc_mod = proto.get("descriptionModule", {})
    cond_mod = proto.get("conditionsModule", {})
    arms_mod = proto.get("armsInterventionsModule", {})
    interventions = [
        iv.get("name", "") for iv in arms_mod.get("interventions", [])
    ]
    return EvidenceRecord(
        identifier=f"NCT:{nct}",
        source_type=SourceType.clinicaltrials,
        source_name="ClinicalTrials.gov",
        url=f"https://clinicaltrials.gov/study/{nct}",
        title=ident_mod.get("briefTitle"),
        product_name=interventions[0] if interventions else None,
        indication=cond_mod.get("conditions", []),
        raw_payload=study,
    )


def _dailymed_to_evidence(item: dict[str, Any]) -> EvidenceRecord | None:
    setid = item.get("setid", "")
    if not setid:
        return None
    drug_name = item.get("drug_name") or item.get("title", "")
    return EvidenceRecord(
        identifier=f"DM:{setid}",
        source_type=SourceType.dailymed_label,
        source_name="DailyMed",
        url=f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}",
        title=drug_name,
        product_name=drug_name,
        raw_payload=item,
    )


def _gudid_to_evidence(result: dict[str, Any]) -> EvidenceRecord | None:
    device = result.get("device") or result if isinstance(result, dict) else {}
    di = device.get("deviceIdentifier", device.get("di", ""))
    if not di:
        return None
    brand = device.get("brandName", "")
    return EvidenceRecord(
        identifier=f"GUDID:{di}",
        source_type=SourceType.accessgudid_device,
        source_name="AccessGUDID",
        url=f"https://accessgudid.nlm.nih.gov/devices/{di}",
        title=brand,
        product_name=brand,
        manufacturer=device.get("companyName", ""),
        raw_payload=result,
    )


def _split_text(text: str, max_tokens: int = 5) -> list[str]:
    """Heuristic: split a long text field into short indication tokens."""
    if not text:
        return []
    tokens = [t.strip() for t in re.split(r"[;,\n]", text) if t.strip()]
    return tokens[:max_tokens]


# ---------------------------------------------------------------------------
# Main expansion function
# ---------------------------------------------------------------------------

async def expand_candidates(
    seed: SeedRecord,
    profile: ExtractedTargetProfile,
    clients: dict[str, Any],
) -> list[EvidenceRecord]:
    """Fetch candidate evidence records from all configured external sources.

    Fans out in parallel to PubMed, openFDA, ClinicalTrials, DailyMed, and
    AccessGUDID based on the seed type and profile fields.  Returns a flat,
    unmerged list of :class:`EvidenceRecord` instances.
    """
    seed_kind = _classify_seed(seed.identifier)

    # Base search term: prefer explicit profile fields, fall back to the seed/query string
    base_q = (profile.product_name or profile.active_ingredient or seed.identifier).strip()

    tasks: list[Any] = []

    # --- PubMed (always) ---
    pubmed_svc = clients.get("pubmed")
    if pubmed_svc is not None:
        keywords = list(profile.indication) + list(profile.key_metrics_or_endpoints)
        q = base_q
        if keywords:
            q += " " + " ".join(keywords[:3])
        tasks.append(_safe(pubmed_svc.search_pubmed(q), "pubmed"))
    else:
        tasks.append(_empty("pubmed"))

    # --- openFDA device/510(k) (always) ---
    openfda = clients.get("openfda")
    if openfda is not None:
        dev_q = profile.product_name or seed.identifier
        tasks.append(_safe(openfda.search_device(dev_q, limit=10), "openfda_device"))
    else:
        tasks.append(_empty("openfda_device"))

    # --- openFDA drug label (always) ---
    if openfda is not None:
        drug_q = profile.active_ingredient or profile.product_name or seed.identifier
        tasks.append(_safe(openfda.search_drug_label(drug_q, limit=10), "openfda_label"))
    else:
        tasks.append(_empty("openfda_label"))

    # --- ClinicalTrials (always) ---
    ct = clients.get("clinicaltrials")
    if ct is not None:
        cond = " ".join(profile.indication[:2]) if profile.indication else None
        intr = profile.product_name or profile.active_ingredient or None
        if cond or intr:
            tasks.append(_safe(ct.search_studies(condition=cond, intervention=intr, limit=10), "clinicaltrials"))
        else:
            # Fall back to free-text query so ClinicalTrials is always searched
            tasks.append(_safe(ct.search_studies(query=seed.identifier, limit=10), "clinicaltrials"))
    else:
        tasks.append(_empty("clinicaltrials"))

    # --- DailyMed (always) ---
    dm = clients.get("dailymed")
    if dm is not None:
        dm_q = profile.active_ingredient or profile.product_name or seed.identifier
        tasks.append(_safe(dm.search_spls(dm_q, limit=10), "dailymed"))
    else:
        tasks.append(_empty("dailymed"))

    # --- AccessGUDID (always) ---
    gudid = clients.get("accessgudid")
    if gudid is not None:
        brand = profile.product_name or seed.identifier
        tasks.append(_safe(gudid.search_devices(brand_name=brand), "accessgudid"))
    else:
        tasks.append(_empty("accessgudid"))

    results = await asyncio.gather(*tasks)
    pubmed_res, openfda_dev_res, openfda_drug_res, ct_res, dm_res, gudid_res = results

    records: list[EvidenceRecord] = []

    # Convert PubMed results
    for item in pubmed_res:
        r = _pubmed_to_evidence(item if isinstance(item, dict) else item.model_dump() if hasattr(item, "model_dump") else {})
        if r:
            records.append(r)

    # Convert openFDA device / 510(k) results
    for item in openfda_dev_res:
        r = _510k_to_evidence(item)
        if r:
            records.append(r)

    # Convert openFDA drug label results
    for item in openfda_drug_res:
        r = _drug_label_to_evidence(item)
        if r:
            records.append(r)

    # Convert ClinicalTrials results
    for study in ct_res:
        r = _trial_to_evidence(study)
        if r:
            records.append(r)

    # Convert DailyMed results
    for item in dm_res:
        r = _dailymed_to_evidence(item)
        if r:
            records.append(r)

    # Convert AccessGUDID results
    for item in gudid_res:
        r = _gudid_to_evidence(item)
        if r:
            records.append(r)

    logger.info(
        "expand_candidates: seed={} kind={} total_raw={}",
        seed.identifier,
        seed_kind,
        len(records),
    )
    return records


async def _safe(coro: Any, label: str) -> list[Any]:
    """Await a coroutine, returning [] on any exception."""
    try:
        result = await coro
        return result if isinstance(result, list) else []
    except Exception as exc:
        logger.warning("expand_candidates: {} failed: {}", label, exc)
        return []


async def _empty(_label: str) -> list[Any]:
    return []
