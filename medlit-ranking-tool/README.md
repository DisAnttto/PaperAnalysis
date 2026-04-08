# MedLit Ranking Tool

Automated ingestion, extraction, and ranking of medical literature using LLMs and evidence-based scoring.

## Overview

MedLit Ranking Tool fetches papers from sources like PubMed, extracts structured data, and ranks them by relevance, novelty, and evidence level — giving researchers a prioritised reading list.

## Project Structure

```
medlit-ranking-tool/
├─ app/
│  ├─ api/          # FastAPI routers
│  ├─ core/         # Config, logging, shared utilities
│  ├─ models/       # Pydantic data models
│  ├─ services/     # Business logic / orchestration
│  ├─ ranking/      # Scoring and ranking algorithms
│  ├─ ingestion/    # Data source connectors (PubMed, etc.)
│  ├─ extraction/   # PDF parsing, field extraction
│  └─ main.py       # FastAPI app entry point
├─ tests/           # Pytest test suite
├─ scripts/         # One-off utility scripts
├─ docs/            # Extended documentation
├─ data/
│  └─ sample/       # Sample datasets (tracked by git)
└─ .cursor/rules/   # Cursor AI project rules
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

# 4. Run the API server
uvicorn app.main:app --reload

# 5. Run tests
pytest
```

## Requirements

- Python 3.11+
- OpenAI API key (for LLM-based extraction and scoring)
- NCBI API key (optional, increases PubMed rate limits)
