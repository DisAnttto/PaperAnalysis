"""Report generator: produce Methods sections, PRISMA flow, and evidence tables.

Generates structured reports from search results for use in regulatory
submissions. Outputs include:
  - Methods section (search strategy, databases, date range, inclusion/exclusion)
  - PRISMA flow diagram data (record counts at each stage)
  - Evidence summary table
  - Markdown and plain-text export formats
"""

from __future__ import annotations

from app.models.ranking import RankedPaperResponse
from app.models.report import (
    EvidenceTableRow,
    PRISMAFlowCounts,
    ReportSection,
    SearchReport,
)
from app.models.run_log import StageCounts
from app.models.search import SearchRequest


def build_prisma_counts(stage_counts: StageCounts) -> PRISMAFlowCounts:
    """Convert pipeline StageCounts into PRISMA flow format."""
    total = stage_counts.pool_total
    post_dedup = stage_counts.post_dedup
    post_triage = stage_counts.post_triage
    post_extraction = stage_counts.post_extraction
    final = stage_counts.final_ranked

    return PRISMAFlowCounts(
        records_identified=stage_counts.pool_per_source,
        total_identified=total,
        duplicates_removed=max(0, total - post_dedup),
        records_screened=post_dedup,
        records_excluded_triage=max(0, post_dedup - post_triage),
        full_text_assessed=post_triage,
        full_text_excluded=max(0, post_triage - post_extraction),
        studies_included=final,
    )


def build_methods_section(
    request: SearchRequest,
    stage_counts: StageCounts,
    run_id: str | None = None,
) -> ReportSection:
    """Generate a Methods section describing the search strategy."""
    sources = list(stage_counts.pool_per_source.keys())
    source_str = ", ".join(sources) if sources else "PubMed"

    date_range = ""
    if request.min_year or request.max_year:
        lo = request.min_year or "inception"
        hi = request.max_year or "present"
        date_range = f" Publication dates were restricted to {lo}–{hi}."

    filters = []
    if request.journal_filter:
        filters.append(f"journals: {', '.join(request.journal_filter)}")
    if request.author_filter:
        filters.append(f"authors: {', '.join(request.author_filter)}")
    if request.include_terms:
        filters.append(f"required terms: {', '.join(request.include_terms)}")
    if request.exclude_terms:
        filters.append(f"excluded terms: {', '.join(request.exclude_terms)}")
    filter_str = (
        " Post-retrieval filters applied: " + "; ".join(filters) + "."
        if filters else ""
    )

    prisma = build_prisma_counts(stage_counts)
    content = (
        f"A systematic literature search was conducted across the following "
        f"databases: {source_str}. The search query was: \"{request.query}\"."
        f"{date_range}{filter_str}\n\n"
        f"A total of {prisma.total_identified} records were identified across "
        f"all databases. After removing {prisma.duplicates_removed} duplicate(s), "
        f"{prisma.records_screened} records were screened using a hybrid "
        f"deterministic and AI-based triage process. Of these, "
        f"{prisma.records_excluded_triage} were excluded during triage, "
        f"leaving {prisma.full_text_assessed} for full-text assessment "
        f"(LLM extraction and normalisation). "
        f"{prisma.studies_included} studies were included in the final analysis."
    )

    if run_id:
        content += f"\n\n[Run ID: {run_id}]"

    return ReportSection(
        heading="Methods: Literature Search Strategy",
        content=content,
        section_type="text",
    )


def build_evidence_table(
    ranked: list[RankedPaperResponse],
) -> list[EvidenceTableRow]:
    """Convert ranked results into evidence table rows."""
    rows: list[EvidenceTableRow] = []
    for r in ranked:
        rows.append(EvidenceTableRow(
            uid=r.pmid or "",
            title=r.title or "",
            source=getattr(r, "source", "PubMed"),
            authors="",
            year=None,
            composite_score=r.composite_score,
            relevance_score=r.relevance_score,
            evidence_quality_score=r.evidence_quality_score,
        ))
    return rows


def generate_report(
    request: SearchRequest,
    ranked: list[RankedPaperResponse],
    stage_counts: StageCounts,
    run_id: str | None = None,
) -> SearchReport:
    """Generate a complete search report."""
    prisma = build_prisma_counts(stage_counts)
    methods = build_methods_section(request, stage_counts, run_id)
    evidence = build_evidence_table(ranked)

    sections = [methods]

    # PRISMA section
    prisma_lines = [
        f"Records identified: {prisma.total_identified}",
    ]
    for src, count in prisma.records_identified.items():
        prisma_lines.append(f"  - {src}: {count}")
    prisma_lines.extend([
        f"Duplicates removed: {prisma.duplicates_removed}",
        f"Records screened: {prisma.records_screened}",
        f"Excluded at triage: {prisma.records_excluded_triage}",
        f"Full-text assessed: {prisma.full_text_assessed}",
        f"Studies included: {prisma.studies_included}",
    ])
    sections.append(ReportSection(
        heading="PRISMA Flow Summary",
        content="\n".join(prisma_lines),
        section_type="prisma",
    ))

    return SearchReport(
        title=f"Literature Search Report: {request.query[:80]}",
        run_id=run_id,
        query=request.query,
        sections=sections,
        prisma=prisma,
        evidence_table=evidence,
    )


def report_to_markdown(report: SearchReport) -> str:
    """Render a SearchReport as markdown text."""
    parts: list[str] = [f"# {report.title}\n"]

    if report.run_id:
        parts.append(f"**Run ID:** {report.run_id}\n")
    parts.append(f"**Query:** {report.query}\n")

    for section in report.sections:
        parts.append(f"\n## {section.heading}\n")
        parts.append(section.content)

    if report.evidence_table:
        parts.append("\n## Evidence Summary Table\n")
        parts.append("| # | UID | Title | Composite | Relevance | Evidence Quality |")
        parts.append("|---|-----|-------|-----------|-----------|-----------------|")
        for i, row in enumerate(report.evidence_table, 1):
            parts.append(
                f"| {i} | {row.uid} | {row.title[:60]} | "
                f"{row.composite_score:.3f} | {row.relevance_score:.3f} | "
                f"{row.evidence_quality_score:.3f} |"
            )

    return "\n".join(parts)
