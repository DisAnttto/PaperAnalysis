"""Compare live search JSON responses to case expectations."""

from __future__ import annotations

from typing import Any

from .models import CaseExpectations

# Glaucoma-procedure title terms — mirrors app/services/triage._GLAUCOMA_PROCEDURE_TERMS.
# Kept in sync manually; used to detect combined-procedure papers that should not
# dominate top results when the target is a non-glaucoma device (e.g. IOL).
_GLAUCOMA_PROCEDURE_TERMS = frozenset({
    "trabeculectomy",
    "trabeculotomy",
    "goniotomy",
    "goniosynechialysis",
    "canaloplasty",
    "viscocanalostomy",
    "gatt",
    "trabectome",
})


def expectation_failures(result: dict[str, Any], exp: CaseExpectations) -> list[str]:
    """Return human-readable failure messages; empty list means all expectations met."""
    rows = result.get("results") or []
    pmid_to_row: dict[str, dict[str, Any]] = {}
    for r in rows:
        pmid = r.get("pmid")
        if pmid is not None:
            pmid_to_row[str(pmid)] = r

    failures: list[str] = []

    # --- PMID presence ---
    for pmid in exp.golden_pmids:
        if pmid not in pmid_to_row:
            failures.append(f"golden PMID {pmid} not in results")

    golden_set = set(exp.golden_pmids)

    # --- Composite score floors ---
    for pmid, min_c in exp.min_composite_by_pmid.items():
        row = pmid_to_row.get(pmid)
        if row is None:
            if pmid not in golden_set:
                failures.append(
                    f"PMID {pmid} not in results (required by min_composite_by_pmid)"
                )
            continue
        got = row.get("composite_score")
        if got is None or float(got) < float(min_c):
            failures.append(
                f"PMID {pmid} composite_score {got!r} < required {min_c}"
            )

    # --- Rank ceilings ---
    for pmid, max_rank in exp.max_rank_by_pmid.items():
        row = pmid_to_row.get(pmid)
        if row is None:
            if pmid not in golden_set:
                failures.append(
                    f"PMID {pmid} not in results (required by max_rank_by_pmid)"
                )
            continue
        rank = row.get("rank")
        if rank is None or int(rank) > int(max_rank):
            failures.append(
                f"PMID {pmid} rank {rank!r} > max allowed {max_rank}"
            )

    # --- M dimension: minimum count of results with metric_favorability_score > 0 ---
    if exp.min_m_nonzero_count is not None:
        m_nonzero = sum(
            1 for r in rows
            if (r.get("metric_favorability_score") or 0.0) > 0.0
        )
        if m_nonzero < exp.min_m_nonzero_count:
            failures.append(
                f"M dimension under-active: {m_nonzero} results have "
                f"metric_favorability_score > 0, required >= {exp.min_m_nonzero_count}. "
                f"Check that metrics_of_interest is non-empty in the request."
            )

    # --- Glaucoma-procedure cap: at most max_count combined-procedure papers in top N ---
    if exp.max_glaucoma_procedure_in_top_n is not None:
        max_count, top_n = exp.max_glaucoma_procedure_in_top_n
        top_rows = sorted(rows, key=lambda r: r.get("rank") or 9999)[:top_n]
        glaucoma_hits = [
            r for r in top_rows
            if any(
                term in (r.get("title") or "").lower()
                for term in _GLAUCOMA_PROCEDURE_TERMS
            )
        ]
        if len(glaucoma_hits) > max_count:
            titles = [r.get("title", "?") for r in glaucoma_hits]
            failures.append(
                f"Glaucoma-procedure papers dominate top {top_n}: "
                f"found {len(glaucoma_hits)} (max allowed {max_count}). "
                f"Titles: {titles}"
            )

    return failures
