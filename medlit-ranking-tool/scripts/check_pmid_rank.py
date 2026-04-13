"""Ad-hoc: find PubMed rank for PMID 39350227 under various queries."""

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from app.services.pubmed import search_pmids


async def rank(q: str) -> tuple[int | None, int]:
    pmids = await search_pmids(q, max_results=100)
    t = "39350227"
    return (pmids.index(t) if t in pmids else None, len(pmids))


async def main() -> None:
    queries = [
        (
            "current built query",
            "faricimab[Title/Abstract] AND (nAMD[Title/Abstract] OR "
            '"neovascular age-related macular degeneration"[Title/Abstract] OR '
            '"neovascular age related macular degeneration"[Title/Abstract] OR '
            '"treatment naive"[Title/Abstract])',
        ),
        (
            "prospective + neovascular",
            "faricimab[Title/Abstract] AND prospective[Title/Abstract] AND "
            "(nAMD[Title/Abstract] OR neovascular[Title/Abstract])",
        ),
        (
            "real-world + neovascular",
            "faricimab[Title/Abstract] AND (real-world[Title/Abstract] OR "
            '"real world"[Title/Abstract]) AND (nAMD[Title/Abstract] OR neovascular[Title/Abstract])',
        ),
        (
            "built + prospective AND",
            "faricimab[Title/Abstract] AND (nAMD[Title/Abstract] OR "
            '"neovascular age-related macular degeneration"[Title/Abstract] OR '
            '"neovascular age related macular degeneration"[Title/Abstract] OR '
            '"treatment naive"[Title/Abstract]) AND prospective[Title/Abstract]',
        ),
    ]
    for label, q in queries:
        i, n = await rank(q)
        print(f"{label}: rank={i} n={n}")


if __name__ == "__main__":
    asyncio.run(main())
