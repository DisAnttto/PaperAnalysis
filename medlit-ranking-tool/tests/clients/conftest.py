"""Shared fixtures for client tests."""

from __future__ import annotations

import pytest

from app.core.config import Settings


@pytest.fixture()
def test_settings() -> Settings:
    """Settings instance with safe test defaults (no real API keys)."""
    return Settings(
        OPENFDA_API_KEY="test-key",
        OPENFDA_BASE_URL="https://api.fda.gov",
        CLINICALTRIALS_BASE_URL="https://clinicaltrials.gov/api/v2",
        ACCESSGUDID_BASE_URL="https://accessgudid.nlm.nih.gov/api/v2",
        DAILYMED_BASE_URL="https://dailymed.nlm.nih.gov/dailymed/services/v2",
    )
