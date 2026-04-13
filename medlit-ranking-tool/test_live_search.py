"""Live search: POST /api/v1/search for a case from tests/collection/cases.json.

Conservative defaults; use --case or LIVE_CASE_ID to pick a case.
Exit: 0 pass, 1 HTTP/transport error, 2 expectation failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from tests.collection import get_case, load_cases
from tests.collection.checks import expectation_failures


def _resolve_case_id(cli_id: str | None) -> str:
    if cli_id:
        return cli_id
    env = os.environ.get("LIVE_CASE_ID", "").strip()
    if env:
        return env
    cases = load_cases()
    if not cases:
        print("ERROR: no cases in collection")
        sys.exit(1)
    return cases[0].id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live POST /api/v1/search using a collection case."
    )
    parser.add_argument(
        "--case",
        dest="case_id",
        default=None,
        help="Case id from tests/collection/cases.json (default: first case or LIVE_CASE_ID)",
    )
    args = parser.parse_args()

    case_id = _resolve_case_id(args.case_id)
    case = get_case(case_id)
    if case is None:
        print(f"ERROR: unknown case id {case_id!r}")
        sys.exit(1)

    payload = case.request.model_dump(mode="json")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/search",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=1200)
        result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace") if e.fp else ""
        print(f"ERROR: HTTP {e.code}: {body[:500]}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    golden = set(case.expectations.golden_pmids)

    print(f"Case: {case.id} — {case.name}")
    print(f"Mode: {result.get('mode')}")
    print(f"Total results: {result.get('total')}")
    print()

    for r in result.get("results", []):
        pmid = r.get("pmid", "?")
        score = r.get("composite_score", 0)
        title = (r.get("title") or "")[:90]
        R = r.get("relevance_score", 0)
        P = r.get("product_similarity_score", 0)
        M = r.get("metric_favorability_score", 0)
        E = r.get("evidence_quality_score", 0)
        marker = " <<<< TARGET" if str(pmid) in golden else ""
        print(
            f"#{r.get('rank', '?')} PMID={pmid} C={score:.4f} "
            f"R={R:.4f} P={P:.4f} M={M:.4f} E={E:.4f}{marker}"
        )
        print(f"   {title}")
        if str(pmid) in golden:
            print(f"   >>> Weights: {r.get('weights_used')}")
            print(f"   >>> Dims excluded: {r.get('dimensions_excluded')}")
            print(
                f"   >>> M est: {r.get('metric_score_estimated')}, "
                f"M inc: {r.get('metric_score_incomplete')}"
            )
            print(f"   >>> E est: {r.get('evidence_score_estimated')}")
            rationale = r.get("ranking_rationale", "") or ""
            print(f"   >>> Rationale: {rationale[:200]}")
            em = r.get("extracted_metrics", [])
            if em:
                print(f"   >>> Extracted metrics ({len(em)}):")
                for m in em[:8]:
                    print(
                        f"       - {m.get('metric_name')}: "
                        f"{m.get('numeric_value')} ({m.get('value_type')})"
                    )
        print()

    failures = expectation_failures(result, case.expectations)
    if failures:
        for msg in failures:
            print(f"FAIL: {msg}")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
