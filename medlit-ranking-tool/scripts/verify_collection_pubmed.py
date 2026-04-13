"""Verify each live-collection case: golden PMID appears in first N PubMed hits.

Run from repo root: py -3 scripts/verify_collection_pubmed.py
Requires NCBI_EMAIL (and optional NCBI_API_KEY) in .env.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# package root
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.collection import load_cases  # noqa: E402

from app.services.pubmed import build_pubmed_query, search_pmids  # noqa: E402


async def main() -> None:
    pool = 30
    failures = 0
    for case in load_cases():
        golden = case.expectations.golden_pmids[0] if case.expectations.golden_pmids else None
        if not golden:
            continue
        tp = case.request.target_product
        q = build_pubmed_query(
            case.request.query,
            tp,
            case.request.keywords or None,
        )
        pmids = await search_pmids(q, max_results=pool)
        if golden in pmids:
            rank = pmids.index(golden) + 1
            print(f"OK  {case.id}: PMID {golden} at rank {rank}/{len(pmids)}")
        else:
            print(f"FAIL {case.id}: PMID {golden} not in top {pool}. Query: {q[:120]}...")
            failures += 1
    raise SystemExit(failures)


if __name__ == "__main__":
    asyncio.run(main())
