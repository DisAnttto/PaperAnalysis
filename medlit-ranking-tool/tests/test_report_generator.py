"""Unit tests for the report generator."""

import pytest

from app.models.ranking import RankedPaperResponse
from app.models.run_log import StageCounts
from app.models.search import SearchRequest
from app.services.report_generator import (
    build_evidence_table,
    build_methods_section,
    build_prisma_counts,
    generate_report,
    report_to_markdown,
)


def _counts() -> StageCounts:
    return StageCounts(
        pool_per_source={"PubMed": 30, "OpenAlex": 20, "openFDA_device": 10},
        pool_total=60,
        post_dedup=50,
        post_triage=10,
        post_extraction=10,
        final_ranked=8,
    )


def _request(**kw) -> SearchRequest:
    defaults = {"query": "faricimab nAMD efficacy", "pool_size": 100, "max_results": 20}
    defaults.update(kw)
    return SearchRequest(**defaults)


def _ranked(pmid: str, composite: float = 0.5) -> RankedPaperResponse:
    return RankedPaperResponse(
        pmid=pmid,
        title=f"Paper {pmid}",
        rank=1,
        composite_score=composite,
        relevance_score=0.5,
        product_similarity_score=0.0,
        metric_favorability_score=0.0,
        evidence_quality_score=0.6,
        weights_used={"R": 0.4, "P": 0.2, "M": 0.2, "E": 0.2},
    )


class TestBuildPrismaCounts:
    def test_counts_add_up(self):
        counts = _counts()
        prisma = build_prisma_counts(counts)
        assert prisma.total_identified == 60
        assert prisma.duplicates_removed == 10
        assert prisma.records_screened == 50
        assert prisma.records_excluded_triage == 40
        assert prisma.full_text_assessed == 10
        assert prisma.studies_included == 8

    def test_per_source_preserved(self):
        counts = _counts()
        prisma = build_prisma_counts(counts)
        assert prisma.records_identified["PubMed"] == 30
        assert prisma.records_identified["OpenAlex"] == 20


class TestBuildMethodsSection:
    def test_mentions_query(self):
        section = build_methods_section(_request(), _counts())
        assert "faricimab nAMD efficacy" in section.content

    def test_mentions_databases(self):
        section = build_methods_section(_request(), _counts())
        assert "PubMed" in section.content

    def test_includes_run_id(self):
        section = build_methods_section(_request(), _counts(), run_id="abc-123")
        assert "abc-123" in section.content

    def test_mentions_filters(self):
        req = _request(journal_filter=["JAMA"], exclude_terms=["animal"])
        section = build_methods_section(req, _counts())
        assert "JAMA" in section.content
        assert "animal" in section.content


class TestBuildEvidenceTable:
    def test_converts_ranked_to_rows(self):
        ranked = [_ranked("1"), _ranked("2")]
        rows = build_evidence_table(ranked)
        assert len(rows) == 2
        assert rows[0].uid == "1"
        assert rows[1].uid == "2"


class TestGenerateReport:
    def test_produces_complete_report(self):
        report = generate_report(
            _request(),
            [_ranked("1")],
            _counts(),
            run_id="test-run",
        )
        assert report.title.startswith("Literature Search Report")
        assert report.run_id == "test-run"
        assert len(report.sections) == 2  # Methods + PRISMA
        assert len(report.evidence_table) == 1
        assert report.prisma.total_identified == 60


class TestReportToMarkdown:
    def test_produces_markdown(self):
        report = generate_report(_request(), [_ranked("1")], _counts())
        md = report_to_markdown(report)
        assert "# Literature Search Report" in md
        assert "## Methods" in md
        assert "## PRISMA" in md
        assert "## Evidence Summary Table" in md
        assert "Paper 1" in md
