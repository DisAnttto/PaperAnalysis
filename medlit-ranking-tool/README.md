# MedLit Ranking Tool

Automated ingestion, extraction, and ranking of medical literature using LLMs and evidence-based scoring.

## Overview

MedLit Ranking Tool fetches papers from PubMed, OpenAlex, openFDA, ClinicalTrials.gov, DailyMed, and AccessGUDID, extracts structured data via LLM, and ranks results by relevance, product similarity, metric favorability, and evidence quality — giving researchers a prioritised reading list for regulatory and clinical evidence work.

## Project Structure

```
medlit-ranking-tool/
├─ app/
│  ├─ api/            # FastAPI routers: health, search, papers, admin, qa,
│  │                  #   retrieval, interpret, report; shared models.py
│  ├─ clients/        # Async HTTP clients: openFDA, OpenAlex, ClinicalTrials,
│  │                  #   DailyMed, AccessGUDID, FDA PDF downloads
│  ├─ core/           # Config (two-tier LLM, NIM, external APIs), logging
│  ├─ demo/           # Seeded fixtures for demo/QA mode
│  ├─ models/         # Pydantic domain models: paper, search, extraction,
│  │                  #   normalized, ranking, interpret, run_log, report
│  ├─ normalization/  # Registry + anatomy, devices, drugs, materials normalizers
│  ├─ ranking/        # R/P/M/E scoring algorithms + composite ranker
│  ├─ retrieval/      # Correlated-evidence pipeline: expansion, fusion,
│  │                  #   graph, scoring, models, enums; demo CLI
│  ├─ retrieval_bench/# Benchmark harness + targets.json
│  ├─ services/       # Orchestration: pool, triage, extraction, pubmed,
│  │                  #   interpret, db, intent_router, post_filters,
│  │                  #   report_generator, rewrite_generator
│  ├─ static/         # QA console CSS + JS
│  ├─ templates/      # Jinja2 HTML templates (QA console)
│  └─ main.py         # FastAPI app entry point
├─ tests/
│  ├─ clients/        # Unit tests for external API clients
│  ├─ collection/     # Gold cases JSON, loaders, manifest tests
│  ├─ integration/    # TestClient end-to-end tests (search, health, papers,
│  │                  #   demo, retrieval UI; gated gold/live)
│  ├─ normalization/  # Unit tests for normalization layer
│  ├─ ranking/        # Unit tests for scoring modules
│  ├─ retrieval/      # Unit tests for retrieval pipeline
│  ├─ retrieval_bench/# Slow benchmark tests (@pytest.mark.slow)
│  └─ services/       # PubMed query builder, extraction coerce tests
├─ docs/              # Extended documentation
├─ scripts/           # dev_server, smoke_nim_llm, check_pmid_rank,
│                     #   verify_collection_pubmed
└─ .env.example       # Environment variable reference
```

## Quickstart

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 4. Run the API server (recommended — avoids “port already in use”)
py -3 scripts/dev_server.py
# Or fixed port:
# uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 5. Run tests
pytest
```

### Dev server won’t start (Windows: port 8000 in use)

If you see **`[WinError 10048]`** or **“only one usage of each socket address”**, another process (often a leftover `uvicorn --reload`) is still listening on **8000**.

1. Find the PID: `netstat -ano | findstr :8000` (look for rows in **LISTENING**).
2. Stop it: `taskkill /PID <pid> /F`
3. Or use the launcher above — it tries **8001**, **8010**, **8765** if **8000** is busy.
4. Or pin a port: `$env:MEDLIT_PORT="8001"; py -3 scripts/dev_server.py`

### Live gold regression (PubMed + LLM)

Direct service tests for `tests/collection/cases.json` (pool + triage survival, then
single-paper extract + composite score). Requires NCBI and LLM keys in `.env`:

```powershell
# Windows PowerShell
$env:RUN_GOLD_PIPELINE="1"
pytest tests/integration/test_gold_pipeline.py -v
```

## QA Console (Internal Validation UI)

The repo ships with a minimal internal QA console for exercising the backend
without any external dependencies.  It is **not** a production UI.

### Running in demo mode

```bash
# Windows PowerShell
$env:APP_MODE="demo"
uvicorn app.main:app --reload

# macOS / Linux
APP_MODE=demo uvicorn app.main:app --reload
```

Open `http://localhost:8000/` in your browser.

### What demo mode provides

- **No LLM calls, no PubMed calls** — all data comes from seeded ophthalmology fixtures
- **6 pre-built papers** with full extractions and pre-computed normalized products:
  1. Hydrophobic acrylic IOL for cataract (AcrySof IQ, prospective cohort, n=250)
  2. Anti-VEGF ranibizumab for wet AMD (RCT, n=300)
  3. Glaucoma drainage device iStent (retrospective cohort, n=150)
  4. Silicone IOL for cataract (case series, n=80)
  5. Dexamethasone intravitreal implant for DME (RCT, n=200)
  6. Cyclosporine-eluting contact lens for dry eye (in-vitro, n=30)
- **Real deterministic scorer** — ranking weights, normalization, and scores are live

### Console features

| Section | Description |
|---|---|
| Search panel | Free-text query + full `TargetProductProfile` fields + weight sliders |
| Preset buttons | One-click autofill for 5 ophthalmology scenarios |
| Results table | Rank, scores (R/P/M/E), rationale; sortable by any column |
| Detail panel | Per-paper metadata, extraction JSON, normalized product JSON, ranking breakdown |
| Status bar | App mode, LLM provider, PubMed status (live-polled from `/health`) |

### API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | System status + mode info |
| `POST` | `/api/v1/search` | Rank papers against `SearchRequest` |
| `POST` | `/api/v1/search/stream` | SSE streaming search (pool → triage → per-paper results) |
| `GET` | `/api/v1/papers/{uid}` | Paper metadata |
| `POST` | `/api/v1/papers/{uid}/extract` | Extraction result |
| `GET` | `/api/v1/papers/{uid}/detail` | Full detail (paper + extraction + normalized) |
| `POST` | `/api/v1/admin/set-mode` | Toggle `APP_MODE` in process |
| `GET` | `/api/v1/qa/gold-cases` | Gold QA cases for form autofill |
| `POST` | `/api/v1/retrieval/correlate` | Correlated-evidence retrieval from a seed |
| `GET` | `/api/v1/retrieval/benchmark/{target_id}` | Load a benchmark target |
| `POST` | `/api/v1/interpret/parse` | Parse a natural-language clinical brief into search fields |
| `GET` | `/api/v1/report/{run_id}` | Structured PRISMA/Methods report from a completed run |
| `GET` | `/api/v1/report/{run_id}/markdown` | Same report as Markdown |
| `GET` | `/docs` | Auto-generated OpenAPI docs |

## Documentation

| Document | Description |
|---|---|
| [docs/product_spec.md](docs/product_spec.md) | Goals, features, API surface, and safety constraints |
| [docs/ranking_spec.md](docs/ranking_spec.md) | Scoring dimensions, weights, formulas, and tie-breaking rules |
| [docs/extraction_schema.json](docs/extraction_schema.json) | JSON Schema for LLM extraction output (validated by Pydantic) |

## Requirements

- Python 3.11+
- OpenAI API key (for LLM-based extraction and scoring)
- NCBI API key (optional, increases PubMed rate limits)
