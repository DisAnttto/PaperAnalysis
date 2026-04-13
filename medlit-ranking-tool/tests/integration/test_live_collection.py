# Run only when the app is live on 127.0.0.1:8000 with PubMed/LLM keys (RUN_LIVE_COLLECTION=1).

from __future__ import annotations

import os

import httpx
import pytest

from tests.collection import get_case, load_cases
from tests.collection.checks import expectation_failures

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_COLLECTION"),
    reason="Set RUN_LIVE_COLLECTION=1 with server + keys; hits live search.",
)


@pytest.mark.parametrize("case_id", [c.id for c in load_cases()])
def test_live_collection_case(case_id: str) -> None:
    case = get_case(case_id)
    assert case is not None
    body = case.request.model_dump(mode="json")
    with httpx.Client(timeout=1200.0) as client:
        r = client.post("http://127.0.0.1:8000/api/v1/search", json=body)
    r.raise_for_status()
    data = r.json()
    failures = expectation_failures(data, case.expectations)
    assert not failures, "; ".join(failures)
