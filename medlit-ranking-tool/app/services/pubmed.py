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

    ``keywords`` (from ``SearchRequest.keywords``) are split by type:
    - Pure-digit entries: treated as PubMed UIDs (ANDed individually), which
      pins specific PMIDs in the pool for regression tests.
    - Text entries: grouped into a single OR clause so they act as recall
      boosters rather than mandatory filters.  Passing several conceptual
      variants (e.g. "IOP spike", "transient IOP elevation") therefore
      *expands* the pool instead of collapsing it to zero.

    Falls back to the cleaned free-text query when no structured fields apply.
    """
    cleaned = _clean_free_text_query(query)
    parts: list[str] = []

    if target is not None:
        # Anchor: prefer drug/product name, fall back to device_category.
        anchor = (target.active_ingredient or target.product_name or "").strip()
        if not anchor and target.device_category:
            anchor = target.device_category.replace("_", " ").strip()

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

        # Build a context group: anchor OR indications.  This ensures papers
        # about the condition/procedure are retrieved even when they don't
        # mention the exact device name in the title/abstract.
        context_terms: list[str] = []
        if anchor:
            context_terms.append(_title_abstract_term(anchor))
        context_terms.extend(ind_terms)
        context_terms = _dedupe_preserve(context_terms)
        if context_terms:
            if len(context_terms) == 1:
                parts.append(context_terms[0])
            else:
                parts.append("(" + " OR ".join(context_terms) + ")")

        low = cleaned.lower()
        if "prospective" in low.replace("-", " "):
            parts.append(_title_abstract_term("prospective"))

    # Keywords: UIDs are mandatory (AND), text variants are ORed together so
    # they expand recall instead of producing an impossible intersection.
    # Phrases longer than 3 words are poor PubMed phrase queries (too literal),
    # so we keep only the first 3 content words for Title/Abstract matching.
    uid_parts: list[str] = []
    text_kw: list[str] = []
    for raw in keywords or []:
        s = raw.strip()
        if not s:
            continue
        if s.isdigit():
            uid_parts.append(f"{s}[UID]")
        else:
            words = s.split()
            if len(words) > 3:
                s = " ".join(words[:3])
            text_kw.append(_title_abstract_term(s))

    parts.extend(uid_parts)
    if text_kw:
        if len(text_kw) == 1:
            parts.append(text_kw[0])
        else:
            parts.append("(" + " OR ".join(text_kw) + ")")

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


def build_pubmed_query_simplified(
    query: str,
    target: TargetProductProfile | None = None,
) -> str:
    """Build a minimal PubMed query using only anchor + indications (no keywords).

    Used as a fallback when the full structured query (which includes keywords)
    returns 0 results. Dropping keywords prevents over-restrictive ANDs from
    specific numeric values or rare phrases that the LLM may have generated.
    """
    cleaned = _clean_free_text_query(query)
    parts: list[str] = []

    if target is not None:
        anchor = (target.active_ingredient or target.product_name or "").strip()
        if not anchor and target.device_category:
            anchor = target.device_category.replace("_", " ").strip()
        if anchor:
            parts.append(_title_abstract_term(anchor))

        ind_terms: list[str] = []
        for raw in target.indications:
            s = raw.strip().replace("_", " ").replace("-", " ")
            if not s:
                continue
            ind_terms.append(_title_abstract_term(s))

        ind_terms = _dedupe_preserve(ind_terms)
        if ind_terms:
            if len(ind_terms) == 1:
                parts.append(ind_terms[0])
            else:
                parts.append("(" + " OR ".join(ind_terms) + ")")

    if parts:
        return " AND ".join(parts)

    return cleaned or query.strip() or ""


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
    *,
    target: TargetProductProfile | None = None,
    free_text_fallback: str | None = None,
) -> list[Paper]:
    """Full PubMed search pipeline: esearch for PMIDs, then efetch for records.

    If the primary query returns 0 results, two fallback levels are attempted:

    1. Simplified query (anchor + indications only, keywords dropped). This
       catches cases where the LLM generated overly specific keywords (e.g.
       numeric values like "20 mmHg") that produce an impossible AND chain.
    2. Raw free-text fallback string (e.g. the user's original query), which
       is always broad enough to return something.
    """
    pmids = await search_pmids(query, max_results, min_year=min_year, max_year=max_year, country=country)

    if not pmids and target is not None:
        simplified = build_pubmed_query_simplified(free_text_fallback or query, target)
        if simplified and simplified != query:
            logger.warning(
                "PubMed primary query returned 0 — retrying with simplified query: {!r}",
                simplified[:200],
            )
            pmids = await search_pmids(simplified, max_results, min_year=min_year, max_year=max_year, country=country)

    if not pmids and free_text_fallback and free_text_fallback != query:
        logger.warning(
            "PubMed simplified query also returned 0 — falling back to free-text: {!r}",
            free_text_fallback[:200],
        )
        pmids = await search_pmids(free_text_fallback, max_results, min_year=min_year, max_year=max_year, country=country)

    if not pmids:
        return []
    return await fetch_papers(pmids)
