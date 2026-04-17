"""Tests for the two-step NL finding parser (parse_finding_text / /interpret/parse)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_resp(content: str) -> MagicMock:
    """Build a minimal chat-completion mock with the given .content."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    return resp


# ---------------------------------------------------------------------------
# Reusable Step 1 / Step 2 JSON pairs
# ---------------------------------------------------------------------------

_STEP1_IOP = json.dumps({
    "product_context": {
        "name": "AcrySof IQ",
        "name_source": "AcrySof IQ",
        "type": "device",
        "manufacturer": "Alcon",
        "category": "intraocular_lens",
        "intended_use": "cataract surgery",
        "indications": ["cataract"],
        "procedure": "phacoemulsification",
        "active_ingredient": None,
        "drug_class": None,
        "route": None,
    },
    "clinical_finding": {
        "metric": "IOP",
        "unit": "mmHg",
        "timepoint": "POD1",
        "observed": 20,
        "control": 18,
        "significant": True,
    },
    "search_goals": [
        "Papers on IOP outcomes after phacoemulsification cataract surgery"
    ],
    "seed_identifier": None,
})

_STEP2_IOP = json.dumps({
    "metric_name": "IOP", "metric_unit": "mmHg", "timepoint": "POD1",
    "observed_value": 20, "control_value": 18, "is_significant": True,
    "clinical_context": "cataract surgery", "procedure": "phacoemulsification",
    "query": "IOP phacoemulsification cataract surgery outcomes",
    "seed_identifier": None,
    "keywords": ["intraocular pressure", "postoperative"],
    "target_type": "device", "product_name": "AcrySof IQ",
    "manufacturer": "Alcon",
    "device_category": "intraocular_lens", "intended_use": "cataract surgery",
    "indications": ["cataract"], "active_ingredient": None,
    "drug_class": None, "route": None,
    "metrics_of_interest": ["IOP", "BCVA"],
})

_STEP1_DRUG = json.dumps({
    "product_context": {
        "name": "VABYSMO", "type": "drug", "manufacturer": None,
        "category": None, "intended_use": "nAMD",
        "indications": ["nAMD", "DME"], "procedure": None,
        "active_ingredient": "faricimab-svoa",
        "drug_class": "anti_vegf", "route": "intravitreal",
    },
    "clinical_finding": {
        "metric": "BCVA", "unit": "letters", "timepoint": "Month 12",
        "observed": 15, "control": None, "significant": True,
    },
    "search_goals": ["Papers on faricimab BCVA outcomes in nAMD"],
    "seed_identifier": None,
})

_STEP2_DRUG = json.dumps({
    "metric_name": "BCVA", "metric_unit": "letters", "timepoint": "Month 12",
    "observed_value": 15, "control_value": None, "is_significant": True,
    "clinical_context": "nAMD treatment", "procedure": None,
    "query": "faricimab nAMD BCVA outcomes",
    "target_type": "drug", "product_name": "VABYSMO",
    "device_category": None, "intended_use": "nAMD",
    "indications": ["nAMD", "DME"], "active_ingredient": "faricimab-svoa",
    "drug_class": "anti_vegf", "route": "intravitreal",
    "metrics_of_interest": ["BCVA", "CST"],
})

_STEP1_IOL = json.dumps({
    "product_context": {
        "name": "intraocular lens",
        "name_source": "人工晶状体",
        "type": "device",
        "manufacturer": "Eyebright Medical",
        "category": "intraocular_lens",
        "intended_use": "visual correction for aphakia after cataract surgery",
        "indications": ["cataract", "aphakia"],
        "procedure": "phacoemulsification",
        "active_ingredient": None, "drug_class": None, "route": None,
    },
    "clinical_finding": {
        "metric": "IOP", "unit": "mmHg", "timepoint": "POD1",
        "observed": 20, "control": 18, "significant": True,
    },
    "search_goals": [
        "Papers reporting transient IOP elevation after cataract surgery that normalises long-term",
        "Papers where postoperative IOP is around 20 mmHg",
        "Papers arguing that IOP of 20 mmHg is within safe limits",
    ],
    "seed_identifier": None,
})

_STEP2_IOL = json.dumps({
    "metric_name": "IOP", "metric_unit": "mmHg", "timepoint": "POD1",
    "observed_value": 20, "control_value": 18, "is_significant": True,
    "clinical_context": "cataract surgery", "procedure": "phacoemulsification",
    "query": "intraocular pressure postoperative cataract surgery intraocular lens transient elevation safety",
    "seed_identifier": None,
    "keywords": ["IOP", "20 mmHg", "postoperative", "transient", "safe range"],
    "target_type": "device", "product_name": None,
    "manufacturer": "Eyebright Medical",
    "device_category": "intraocular_lens",
    "intended_use": "visual correction for aphakia after cataract surgery",
    "indications": ["cataract", "aphakia"],
    "active_ingredient": None, "drug_class": None, "route": None,
    "metrics_of_interest": ["IOP", "BCVA"],
})


# ---------------------------------------------------------------------------
# TestParseFindingText — service function (two-step chain)
# ---------------------------------------------------------------------------

class TestParseFindingText:

    @pytest.mark.asyncio
    async def test_parse_returns_structured_fields(self):
        from app.services.interpret import parse_finding_text

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(_STEP1_IOP), _mock_resp(_STEP2_IOP)]
            )
            result = await parse_finding_text("术后1天眼压20mmHg vs 18mmHg")

        assert result.metric_name == "IOP"
        assert result.metric_unit == "mmHg"
        assert result.observed_value == 20.0
        assert result.control_value == 18.0
        assert result.timepoint == "POD1"
        assert result.is_significant is True
        assert result.raw_text == "术后1天眼压20mmHg vs 18mmHg"

    @pytest.mark.asyncio
    async def test_parse_echoes_step1_for_ui(self):
        """Step 1 product_context / clinical_finding / search_goals are echoed for the UI."""
        from app.services.interpret import parse_finding_text

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(_STEP1_IOP), _mock_resp(_STEP2_IOP)]
            )
            result = await parse_finding_text("test")

        assert result.step1_product_context is not None
        assert result.step1_product_context.get("name_source") == "AcrySof IQ"
        assert result.step1_clinical_finding is not None
        assert result.step1_clinical_finding.get("metric") == "IOP"
        assert result.step1_clinical_finding.get("observed") == 20
        assert result.step1_search_goals == [
            "Papers on IOP outcomes after phacoemulsification cataract surgery",
        ]

    @pytest.mark.asyncio
    async def test_parse_fills_main_search_fields(self):
        """Step 2 populates device/drug/query/metrics for sidebar."""
        from app.services.interpret import parse_finding_text

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(_STEP1_IOP), _mock_resp(_STEP2_IOP)]
            )
            result = await parse_finding_text("AcrySof IQ IOP POD1 20 vs 18 mmHg cataract surgery")

        assert result.query == "IOP phacoemulsification cataract surgery outcomes"
        assert result.target_type == "device"
        assert result.product_name == "AcrySof IQ"
        assert result.manufacturer == "Alcon"
        assert result.device_category == "intraocular_lens"
        assert result.intended_use == "cataract surgery"
        assert result.indications == ["cataract"]
        assert result.metrics_of_interest == ["IOP", "BCVA"]
        assert result.active_ingredient is None
        assert result.route is None
        assert result.seed_identifier is None
        assert result.keywords == ["intraocular pressure", "postoperative"]

    @pytest.mark.asyncio
    async def test_parse_drug_fields(self):
        """Drug context populates active_ingredient, drug_class, route."""
        from app.services.interpret import parse_finding_text

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(_STEP1_DRUG), _mock_resp(_STEP2_DRUG)]
            )
            result = await parse_finding_text("faricimab BCVA gain 15 letters at Month 12, significant")

        assert result.active_ingredient == "faricimab-svoa"
        assert result.drug_class == "anti_vegf"
        assert result.route == "intravitreal"
        assert result.target_type == "drug"
        assert result.indications == ["nAMD", "DME"]

    @pytest.mark.asyncio
    async def test_parse_iol_intent_driven(self):
        """IOL research brief: query captures search intent, not product echo."""
        from app.services.interpret import parse_finding_text

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(_STEP1_IOL), _mock_resp(_STEP2_IOL)]
            )
            result = await parse_finding_text(
                "人工晶状体,-10.0～+36.0 D，以白内障患者为代表人群，"
                "评价爱博诺德公司生产的人工晶状体安全性和有效性。"
                "术后1天试验组眼压20mmHg，对照组18mmHg。"
                "搜集术后短期眼压升高长期恢复正常的文献"
            )

        assert "transient" in result.query or "elevation" in result.query
        assert "safety" in result.query or "safe" in result.query
        assert result.manufacturer == "Eyebright Medical"
        assert result.device_category == "intraocular_lens"
        assert result.intended_use is not None
        assert result.indications is not None
        assert "cataract" in result.indications
        assert result.metrics_of_interest is not None
        assert "IOP" in result.metrics_of_interest
        assert result.keywords is not None
        assert len(result.keywords) >= 3
        assert result.seed_identifier is None
        assert result.observed_value == 20.0
        assert result.control_value == 18.0
        assert result.step1_product_context is not None
        assert result.step1_product_context.get("name_source") == "人工晶状体"
        assert result.step1_clinical_finding is not None
        assert result.step1_clinical_finding.get("metric") == "IOP"

    @pytest.mark.asyncio
    async def test_two_llm_calls_made(self):
        """Verify that parse_finding_text makes exactly 2 LLM calls."""
        from app.services.interpret import parse_finding_text

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            mock_create = AsyncMock(
                side_effect=[_mock_resp(_STEP1_IOP), _mock_resp(_STEP2_IOP)]
            )
            instance.chat.completions.create = mock_create
            await parse_finding_text("IOP 20 mmHg")

        assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_parse_handles_partial_step2(self):
        """Step 2 with sparse output still maps available fields."""
        from app.services.interpret import parse_finding_text

        step1_minimal = json.dumps({
            "product_context": None,
            "clinical_finding": {"metric": "BCVA", "unit": None,
                                 "timepoint": None, "observed": 0.5,
                                 "control": None, "significant": None},
            "search_goals": [],
            "seed_identifier": None,
        })
        step2_minimal = '{"metric_name":"BCVA","observed_value":0.5}'

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(step1_minimal), _mock_resp(step2_minimal)]
            )
            result = await parse_finding_text("visual acuity was 0.5")

        assert result.metric_name == "BCVA"
        assert result.observed_value == 0.5
        assert result.control_value is None
        assert result.query is None

    @pytest.mark.asyncio
    async def test_parse_seed_identifier_and_keywords(self):
        """Seed and keywords flow through both steps correctly."""
        from app.services.interpret import parse_finding_text

        step1_seed = json.dumps({
            "product_context": {
                "name": "VABYSMO", "type": "drug", "manufacturer": None,
                "category": None, "intended_use": "nAMD",
                "indications": ["nAMD"], "procedure": None,
                "active_ingredient": "faricimab-svoa",
                "drug_class": "anti_vegf", "route": "intravitreal",
            },
            "clinical_finding": None,
            "search_goals": ["Papers on faricimab nAMD outcomes"],
            "seed_identifier": "PMID:39350227",
        })
        step2_seed = json.dumps({
            "metric_name": None, "metric_unit": None, "timepoint": None,
            "observed_value": None, "control_value": None, "is_significant": None,
            "clinical_context": None, "procedure": None,
            "query": "faricimab nAMD outcomes",
            "seed_identifier": "PMID:39350227",
            "keywords": ["39350227", "nAMD", "anti-VEGF"],
            "target_type": "drug", "product_name": "VABYSMO",
            "device_category": None, "intended_use": "nAMD",
            "indications": ["nAMD"], "active_ingredient": "faricimab-svoa",
            "drug_class": "anti_vegf", "route": "intravitreal",
            "metrics_of_interest": ["BCVA", "CST"],
        })

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(step1_seed), _mock_resp(step2_seed)]
            )
            result = await parse_finding_text("PMID:39350227 faricimab nAMD")

        assert result.seed_identifier == "PMID:39350227"
        assert result.keywords == ["39350227", "nAMD", "anti-VEGF"]
        assert result.query == "faricimab nAMD outcomes"

    @pytest.mark.asyncio
    async def test_parse_seed_not_hallucinated(self):
        """seed_identifier stays null when no canonical ID is present."""
        from app.services.interpret import parse_finding_text

        step1_no_id = json.dumps({
            "product_context": None,
            "clinical_finding": {"metric": "IOP", "unit": "mmHg",
                                 "timepoint": None, "observed": 20,
                                 "control": None, "significant": None},
            "search_goals": ["Papers on IOP after cataract surgery"],
            "seed_identifier": None,
        })
        step2_no_id = json.dumps({
            "metric_name": "IOP", "observed_value": 20,
            "query": "IOP cataract surgery",
            "seed_identifier": None, "keywords": None,
            "target_type": "both", "product_name": None,
            "device_category": None, "intended_use": None,
            "indications": None, "active_ingredient": None,
            "drug_class": None, "route": None,
            "metrics_of_interest": ["IOP"],
            "metric_unit": "mmHg", "timepoint": None,
            "control_value": None, "is_significant": None,
            "clinical_context": None, "procedure": None,
        })

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(step1_no_id), _mock_resp(step2_no_id)]
            )
            result = await parse_finding_text("IOP 20 mmHg cataract surgery")

        assert result.seed_identifier is None

    @pytest.mark.asyncio
    async def test_step1_failure_returns_empty(self):
        """If Step 1 fails entirely, return an empty response with raw_text."""
        from app.services.interpret import parse_finding_text

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=RuntimeError("API down")
            )
            result = await parse_finding_text("some text")

        assert result.raw_text == "some text"
        assert result.metric_name is None
        assert result.observed_value is None
        assert result.query is None

    @pytest.mark.asyncio
    async def test_step2_failure_falls_back_to_step1(self):
        """If Step 2 fails, partial fields from Step 1 are still returned."""
        from app.services.interpret import parse_finding_text

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(side_effect=[
                _mock_resp(_STEP1_IOL),
                RuntimeError("Step 2 broke"),
            ])
            result = await parse_finding_text("IOL cataract IOP 20 mmHg")

        assert result.raw_text == "IOL cataract IOP 20 mmHg"
        assert result.manufacturer == "Eyebright Medical"
        assert result.device_category == "intraocular_lens"
        assert result.metric_name == "IOP"
        assert result.observed_value == 20
        assert result.control_value == 18
        assert result.query is not None

    @pytest.mark.asyncio
    async def test_parse_strips_markdown_fences(self):
        """Fenced LLM output on either step is handled."""
        from app.services.interpret import parse_finding_text

        fenced_step1 = '```json\n' + _STEP1_IOP + '\n```'
        fenced_step2 = '```json\n' + _STEP2_IOP + '\n```'

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(fenced_step1), _mock_resp(fenced_step2)]
            )
            result = await parse_finding_text("IOP 22 mmHg")

        assert result.metric_name == "IOP"
        assert result.query is not None


# ---------------------------------------------------------------------------
# TestParseEndpoint — REST API
# ---------------------------------------------------------------------------

class TestParseEndpoint:
    def test_parse_returns_200_with_all_new_fields(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.services.interpret.AsyncOpenAI") as MockClient:
            instance = MockClient.return_value
            instance.chat.completions.create = AsyncMock(
                side_effect=[_mock_resp(_STEP1_IOP), _mock_resp(_STEP2_IOP)]
            )
            client = TestClient(app)
            resp = client.post(
                "/api/v1/interpret/parse",
                json={"text": "IOP 20 vs 18 mmHg POD1 cataract surgery significant"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["metric_name"] == "IOP"
        assert data["observed_value"] == 20.0
        assert data["query"] == "IOP phacoemulsification cataract surgery outcomes"
        assert data["target_type"] == "device"
        assert data["seed_identifier"] is None
        assert data["keywords"] == ["intraocular pressure", "postoperative"]
        assert data["raw_text"] == "IOP 20 vs 18 mmHg POD1 cataract surgery significant"
        assert data["step1_clinical_finding"]["metric"] == "IOP"
        assert data["step1_search_goals"] == [
            "Papers on IOP outcomes after phacoemulsification cataract surgery",
        ]

    def test_parse_empty_text_returns_422(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        resp = client.post("/api/v1/interpret/parse", json={"text": ""})
        assert resp.status_code == 422

    def test_parse_missing_text_returns_422(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        resp = client.post("/api/v1/interpret/parse", json={})
        assert resp.status_code == 422

    def test_old_angle_endpoints_removed(self):
        """Verify /interpret and /interpret/preview are gone."""
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        assert client.post("/api/v1/interpret", json={}).status_code == 404
        assert client.post("/api/v1/interpret/preview", json={}).status_code == 404
        assert client.post("/api/v1/interpret/run", json={}).status_code == 404
