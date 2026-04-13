"""Compare live search JSON responses to case expectations."""

from __future__ import annotations

from typing import Any

from .models import CaseExpectations


def expectation_failures(result: dict[str, Any], exp: CaseExpectations) -> list[str]:
    """Return human-readable failure messages; empty list means all expectations met."""
    rows = result.get("results") or []
    pmid_to_row: dict[str, dict[str, Any]] = {}
    for r in rows:
        pmid = r.get("pmid")
        if pmid is not None:
            pmid_to_row[str(pmid)] = r

    failures: list[str] = []

    for pmid in exp.golden_pmids:
        if pmid not in pmid_to_row:
            failures.append(f"golden PMID {pmid} not in results")

    golden_set = set(exp.golden_pmids)

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

    return failures
