"""CLI demo for the correlated-evidence retrieval pipeline.

Usage:
    python -m app.retrieval.demo_cli --seed "PMID:39350227"
    python -m app.retrieval.demo_cli --seed "DEN180001"
    python -m app.retrieval.demo_cli --seed "K211668"
"""

from __future__ import annotations

import argparse
import asyncio
import json


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run correlated-evidence retrieval for a single seed."
    )
    parser.add_argument(
        "--seed",
        required=True,
        help='Seed identifier, e.g. "PMID:39350227", "DEN180001", "K211668"',
    )
    return parser.parse_args(argv)


async def _main(seed: str) -> None:
    from app.retrieval.pipeline import retrieve_correlated_evidence

    response = await retrieve_correlated_evidence(seed)
    print(json.dumps(response.model_dump(mode="json"), indent=2))


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    asyncio.run(_main(args.seed))


if __name__ == "__main__":
    main()
