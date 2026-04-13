"""PubMed search and fetch via NCBI Entrez E-Utilities.

Uses httpx for async HTTP and lxml for XML parsing.
Requires NCBI_API_KEY (optional but recommended) and NCBI_EMAIL in config.

NCBI Entrez docs: https://www.ncbi.nlm.nih.gov/books/NBK25500/
"""

from datetime import date
from xml.etree import ElementTree as ET

import httpx
from loguru import logger

from app.core.config import settings
from app.models.paper import Paper
from app.models.search import TargetProductProfile

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_TIMEOUT = 60.0
_FETCH_BATCH_SIZE = 25  # NCBI recommends batching large efetch requests


def _clean_free_text_query(query: str) -> str:
    """Normalize user query: hyphens to spaces, collapse whitespace."""
    q = query.strip()
    if not q:
        return q
    q = q.replace("-", " ")
    return " ".join(q.split())


def _title_abstract_term(phrase: str) -> str:
    """Format a phrase for PubMed [Title/Abstract] search.

    Multi-word phrases are quoted so PubMed treats them as a phrase.
    """
    p = phrase.strip()
    if not p:
        return ""
    if " " in p:
        return f'"{p}"[Title/Abstract]'
    return f"{p}[Title/Abstract]"


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_pubmed_query(
    query: str,
    target: TargetProductProfile | None = None,
    keywords: list[str] | None = None,
) -> str:
    """Build a broad PubMed ESearch ``term`` from user text + target profile.

    Raw multi-token queries are over-restrictive (PubMed ANDs tokens). When
    ``target`` has ``active_ingredient`` / ``product_name``, ``indications``, or
    ``device_category``, we combine field-tagged terms with OR inside indication
    groups and AND across groups so the pool is large enough for triage/ranking.

    ``keywords`` (from ``SearchRequest.keywords``) are ANDed as extra Title/Abstract
    phrases. Pure-digit entries are treated as PubMed UIDs (exact articles), which
    helps regression tests keep a known PMID in the pool without changing triage.

    Falls back to the cleaned free-text query when no structured fields apply.
    """
    cleaned = _clean_free_text_query(query)
    parts: list[str] = []

    if target is not None:
        anchor = (target.active_ingredient or target.product_name or "").strip()
        if anchor:
            parts.append(_title_abstract_term(anchor))

        ind_terms: list[str] = []
        for raw in target.indications:
            s = raw.strip().replace("_", " ").replace("-", " ")
            if not s:
                continue
            ind_terms.append(_title_abstract_term(s))
            low = s.lower().rstrip(",")
            if low == "namd":
                ind_terms.append(
                    _title_abstract_term("neovascular age-related macular degeneration")
                )

        ind_terms = _dedupe_preserve(ind_terms)
        if ind_terms:
            if len(ind_terms) == 1:
                parts.append(ind_terms[0])
            else:
                parts.append("(" + " OR ".join(ind_terms) + ")")

        # Optional AND from free-text query (only explicit boosters; keeps pool aligned
        # with user intent — e.g. "prospective" lifts real-world prospective cohorts.)
        low = cleaned.lower()
        if "prospective" in low.replace("-", " "):
            parts.append(_title_abstract_term("prospective"))

    for raw in keywords or []:
        s = raw.strip()
        if not s:
            continue
        if s.isdigit():
            parts.append(f"{s}[UID]")
        else:
            parts.append(_title_abstract_term(s))

    if parts:
        combined = " AND ".join(parts)
        logger.info(
            "PubMed built query from target profile (user query was {!r}): {!r}",
            query[:120],
            combined[:300],
        )
        return combined

    if cleaned:
        logger.info("PubMed query fallback (no structured target fields): {!r}", cleaned[:200])
        return cleaned

    return query.strip() or ""


def _entrez_params() -> dict[str, str]:
    """Common params sent with every Entrez request."""
    params: dict[str, str] = {"db": "pubmed", "retmode": "xml"}
    if settings.NCBI_API_KEY:
        params["api_key"] = settings.NCBI_API_KEY
    if settings.NCBI_EMAIL:
        params["email"] = settings.NCBI_EMAIL
    return params


async def search_pmids(
    query: str,
    max_results: int = 20,
    min_year: int | None = None,
    max_year: int | None = None,
    country: str | None = None,
) -> list[str]:
    """ESearch: return a list of PMIDs matching the query string.

    Optional filters:
    - min_year / max_year: restrict to publication date range (PubMed pdat).
    - country: appended as ``AND <country>[Affiliation]`` to the query term.
    """
    effective_query = query
    if country:
        effective_query += f" AND {country}[Affiliation]"

    params = _entrez_params()
    params.update({
        "term": effective_query,
        "retmax": str(max_results),
        "sort": "relevance",
        "usehistory": "n",
    })

    if min_year or max_year:
        params["datetype"] = "pdat"
        if min_year:
            params["mindate"] = f"{min_year}/01/01"
        if max_year:
            params["maxdate"] = f"{max_year}/12/31"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{_BASE}/esearch.fcgi", params=params)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    pmids = [id_el.text for id_el in root.findall(".//Id") if id_el.text]
    logger.info("PubMed esearch returned {} PMIDs for query: {!r}", len(pmids), query[:80])
    return pmids


def _parse_date(article: ET.Element) -> date | None:
    """Try to extract a publication date from a PubMed article element."""
    for date_tag in ("ArticleDate", "PubDate"):
        date_el = article.find(f".//{date_tag}")
        if date_el is None:
            continue
        y = date_el.findtext("Year")
        m = date_el.findtext("Month") or "1"
        d = date_el.findtext("Day") or "1"
        if y:
            try:
                month_int = int(m) if m.isdigit() else _month_name_to_int(m)
                return date(int(y), month_int, int(d))
            except (ValueError, TypeError):
                pass
    return None


_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _month_name_to_int(name: str) -> int:
    return _MONTH_MAP.get(name.lower()[:3], 1)


def _parse_article(article: ET.Element) -> Paper:
    """Parse a single PubmedArticle XML element into a Paper model."""
    medline = article.find("MedlineCitation")
    art = medline.find("Article") if medline is not None else None

    pmid_el = medline.find("PMID") if medline is not None else None
    pmid = pmid_el.text if pmid_el is not None else None

    title = ""
    if art is not None:
        title_el = art.find("ArticleTitle")
        if title_el is not None and title_el.text:
            title = title_el.text.strip()

    abstract = ""
    if art is not None:
        abs_el = art.find("Abstract")
        if abs_el is not None:
            parts = []
            for at in abs_el.findall("AbstractText"):
                label = at.get("Label", "")
                text = "".join(at.itertext()).strip()
                if label and text:
                    parts.append(f"{label}: {text}")
                elif text:
                    parts.append(text)
            abstract = " ".join(parts)

    authors: list[str] = []
    if art is not None:
        for author in art.findall(".//Author"):
            last = author.findtext("LastName") or ""
            initials = author.findtext("Initials") or ""
            if last:
                authors.append(f"{last} {initials}".strip())

    journal = ""
    if art is not None:
        journal_el = art.find("Journal/Title")
        if journal_el is not None and journal_el.text:
            journal = journal_el.text.strip()

    pub_date = _parse_date(article)

    doi = None
    if art is not None:
        for eid in art.findall("ELocationID"):
            if eid.get("EIdType") == "doi" and eid.text:
                doi = eid.text.strip()
                break

    mesh_terms: list[str] = []
    if medline is not None:
        for mh in medline.findall(".//MeshHeading/DescriptorName"):
            if mh.text:
                mesh_terms.append(mh.text)

    keywords: list[str] = []
    if medline is not None:
        for kw in medline.findall(".//Keyword"):
            if kw.text:
                keywords.append(kw.text)

    return Paper(
        pmid=pmid,
        doi=doi,
        title=title or "(no title)",
        abstract=abstract or None,
        authors=authors,
        journal=journal or None,
        published_date=pub_date,
        mesh_terms=mesh_terms,
        keywords=keywords,
    )


async def _fetch_batch(pmids: list[str]) -> list[Paper]:
    """EFetch a single batch of PMIDs (up to _FETCH_BATCH_SIZE) and parse into Paper objects."""
    params = _entrez_params()
    params["id"] = ",".join(pmids)
    params["rettype"] = "xml"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{_BASE}/efetch.fcgi", params=params)
        resp.raise_for_status()

    root = ET.fromstring(resp.text)
    papers = []
    for article in root.findall("PubmedArticle"):
        try:
            papers.append(_parse_article(article))
        except Exception as exc:
            logger.warning("Failed to parse PubMed article: {}", exc)
    return papers


async def fetch_papers(pmids: list[str]) -> list[Paper]:
    """EFetch: retrieve full PubMed article records and parse into Paper objects.

    Batches requests in groups of ``_FETCH_BATCH_SIZE`` to avoid NCBI timeouts
    when fetching large pools (e.g. 100 papers for the triage pool).
    """
    if not pmids:
        return []

    papers: list[Paper] = []
    for i in range(0, len(pmids), _FETCH_BATCH_SIZE):
        batch = pmids[i : i + _FETCH_BATCH_SIZE]
        try:
            batch_papers = await _fetch_batch(batch)
            papers.extend(batch_papers)
            logger.debug("Fetched batch {}-{}: {} papers", i, i + len(batch), len(batch_papers))
        except Exception as exc:
            logger.warning("Failed to fetch batch {}-{}: {}", i, i + len(batch), exc)

    logger.info("Parsed {} papers from PubMed efetch ({} PMIDs requested)", len(papers), len(pmids))
    return papers


async def search_pubmed(
    query: str,
    max_results: int = 20,
    min_year: int | None = None,
    max_year: int | None = None,
    country: str | None = None,
) -> list[Paper]:
    """Full PubMed search pipeline: esearch for PMIDs, then efetch for records."""
    pmids = await search_pmids(query, max_results, min_year=min_year, max_year=max_year, country=country)
    if not pmids:
        return []
    return await fetch_papers(pmids)
