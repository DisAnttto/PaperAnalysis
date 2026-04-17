"""Unit tests for post-retrieval filters."""

import pytest

from app.models.paper import Paper
from app.models.search import SearchRequest
from app.services.post_filters import apply_post_filters


def _paper(
    pmid: str = "1",
    title: str = "Test",
    abstract: str | None = None,
    journal: str | None = None,
    authors: list[str] | None = None,
) -> Paper:
    return Paper(
        pmid=pmid,
        title=title,
        abstract=abstract,
        journal=journal,
        authors=authors or [],
    )


def _req(**kwargs) -> SearchRequest:
    defaults = {"query": "test query", "pool_size": 10, "max_results": 5}
    defaults.update(kwargs)
    return SearchRequest(**defaults)


class TestJournalFilter:
    def test_includes_matching_journal(self):
        papers = [
            _paper("1", journal="JAMA Ophthalmology"),
            _paper("2", journal="Nature"),
        ]
        req = _req(journal_filter=["JAMA"])
        result = apply_post_filters(papers, req)
        assert len(result) == 1
        assert result[0].pmid == "1"

    def test_no_filter_keeps_all(self):
        papers = [_paper("1"), _paper("2")]
        req = _req()
        assert len(apply_post_filters(papers, req)) == 2

    def test_case_insensitive(self):
        papers = [_paper("1", journal="The Lancet")]
        req = _req(journal_filter=["lancet"])
        assert len(apply_post_filters(papers, req)) == 1


class TestAuthorFilter:
    def test_includes_matching_author(self):
        papers = [
            _paper("1", authors=["Smith J", "Doe A"]),
            _paper("2", authors=["Jones B"]),
        ]
        req = _req(author_filter=["Smith"])
        result = apply_post_filters(papers, req)
        assert len(result) == 1
        assert result[0].pmid == "1"


class TestIncludeTerms:
    def test_must_contain_all(self):
        papers = [
            _paper("1", title="IOP after phaco", abstract="cataract surgery"),
            _paper("2", title="BCVA study"),
        ]
        req = _req(include_terms=["IOP", "cataract"])
        result = apply_post_filters(papers, req)
        assert len(result) == 1
        assert result[0].pmid == "1"


class TestExcludeTerms:
    def test_excludes_any_matching(self):
        papers = [
            _paper("1", title="Safety of device"),
            _paper("2", title="Efficacy study"),
        ]
        req = _req(exclude_terms=["safety"])
        result = apply_post_filters(papers, req)
        assert len(result) == 1
        assert result[0].pmid == "2"


class TestCombined:
    def test_multiple_filters(self):
        papers = [
            _paper("1", title="IOP after phaco", journal="JAMA", authors=["Smith"]),
            _paper("2", title="IOP study", journal="Nature", authors=["Jones"]),
            _paper("3", title="BCVA report", journal="JAMA", authors=["Smith"]),
        ]
        req = _req(
            journal_filter=["JAMA"],
            include_terms=["IOP"],
        )
        result = apply_post_filters(papers, req)
        assert len(result) == 1
        assert result[0].pmid == "1"
