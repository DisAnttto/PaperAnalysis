"""Shared fixtures for integration tests.

All integration tests run with APP_MODE=demo so no LLM or PubMed calls
are made.  ``app.core.config`` loads ``.env`` with higher precedence than
``os.environ`` for ``APP_MODE``, so we mutate ``settings.APP_MODE`` before
importing the FastAPI app.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _demo_env():
    yield


@pytest.fixture(scope="session")
def client(_demo_env):
    import app.core.config as cfg  # noqa: PLC0415

    cfg.settings.APP_MODE = "demo"
    from app.main import app  # noqa: PLC0415

    with TestClient(app) as c:
        yield c
