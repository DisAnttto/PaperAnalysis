"""Post-retrieval filters applied after pool fetch, before triage.

These filters operate on the in-memory Paper objects and use fields from
SearchRequest (journal_filter, author_filter, include_terms, exclude_terms).
They do not require network calls.
"""

from __future__ import annotations

from app.models.paper import Paper
from app.models.search import SearchRequest


def apply_post_filters(
    papers: list[Paper],
    request: SearchRequest,
) -> list[Paper]:
    """Apply all post-retrieval filters and return the surviving papers."""
    result = papers

    if request.journal_filter:
        journals_lower = [j.strip().lower() for j in request.journal_filter if j.strip()]
        if journals_lower:
            result = [
                p for p in result
                if p.journal and any(j in p.journal.lower() for j in journals_lower)
            ]

    if request.author_filter:
        authors_lower = [a.strip().lower() for a in request.author_filter if a.strip()]
        if authors_lower:
            result = [
                p for p in result
                if any(
                    any(a in auth.lower() for a in authors_lower)
                    for auth in p.authors
                )
            ]

    if request.include_terms:
        terms = [t.strip().lower() for t in request.include_terms if t.strip()]
        if terms:
            def _has_all(p: Paper) -> bool:
                text = ((p.title or "") + " " + (p.abstract or "")).lower()
                return all(t in text for t in terms)
            result = [p for p in result if _has_all(p)]

    if request.exclude_terms:
        terms = [t.strip().lower() for t in request.exclude_terms if t.strip()]
        if terms:
            def _has_none(p: Paper) -> bool:
                text = ((p.title or "") + " " + (p.abstract or "")).lower()
                return not any(t in text for t in terms)
            result = [p for p in result if _has_none(p)]

    return result
