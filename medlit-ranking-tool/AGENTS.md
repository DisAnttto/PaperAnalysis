# AGENTS.md

This project is a Python medical-device literature intelligence tool with multi-source search, triage, extraction, ranking, correlated-evidence retrieval, and outcome interpretation.

## Goals

- Search biomedical literature and regulatory databases (PubMed, openFDA, ClinicalTrials.gov, DailyMed, AccessGUDID)
- Extract device/product details and numeric outcomes via LLM
- Generate paper synopsis
- Rank papers by relevance, product similarity, metric favorability, and evidence quality
- Retrieve correlated evidence for FDA submission support
- Interpret clinical outcome observations with evidence-backed angles

## Rules

- Never infer regulatory approval from paper text alone
- Always tie extracted values to evidence text
- If a metric is missing, mark it missing
- Prefer simple, testable code over clever abstractions
- Use typed Python and Pydantic models
- Keep functions small and modular
- Add tests for ranking logic
- Do not commit secrets or API keys

## Code Conventions

- **Language**: Python 3.11+, fully type-annotated (use built-in generics: `list[str]`, `dict[str, Any]`).
- **Style**: Ruff for linting and formatting (line length 88). Run `ruff check . --fix` before committing.
- **Types**: Strict mypy (`mypy app/`). Avoid `Any` unless absolutely necessary.
- **Models**: Use Pydantic v2 `BaseModel` for all data structures.
- **Database**: SQLAlchemy Core (not ORM). DB helpers in `app/services/db.py`. Tables store JSON blobs keyed by `Paper.uid`.
- **Config**: All settings via `app.core.config.Settings` (pydantic-settings). Never hardcode secrets.
- **Logging**: Use `loguru` logger, never `print()`.
- **Tests**: Pytest. New features must include tests. Place tests in `tests/` mirroring the `app/` structure.
- **Ranking**: Scoring must be deterministic and algorithm-driven. LLMs may enrich signals but never produce the final ranking score alone.
- **LLM outputs**: Every LLM response must be parsed into a typed Pydantic model. No string manipulation of raw LLM text.
- **Documentation**: Update `DEVELOPER_NOTES.md` when adding a major component (new router, service, ingestion source, or ranking algorithm).

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `app/api/` | FastAPI routers: `health`, `search`, `papers`, `admin`, `qa`, `retrieval`, `interpret`; shared `models.py` |
| `app/core/` | Config (two-tier LLM, NIM, external APIs), logging, shared helpers |
| `app/models/` | Pydantic domain models: `paper`, `search`, `extraction`, `normalized`, `ranking`, `interpret` |
| `app/services/` | Orchestration: `pool` (multi-source fan-out), `pubmed`, `triage` (split-track), `extraction`, `interpret`, `db` |
| `app/clients/` | Async HTTP clients: openFDA, ClinicalTrials, DailyMed, AccessGUDID, FDA PDF downloads |
| `app/ranking/` | Scoring algorithms: `relevance` + `relevance_agent`, `product_similarity`, `metric_favorability`, `evidence_quality`, `composite` |
| `app/normalization/` | Registry + anatomy, devices, drugs, materials normalizers |
| `app/retrieval/` | Correlated-evidence pipeline: `pipeline`, `expansion`, `fusion`, `graph`, `scoring`, `models`, `enums` |
| `app/demo/` | Demo fixtures for `demo` mode |
| `app/static/`, `app/templates/` | QA Console frontend (vanilla JS + HTML + CSS) |

## Do Not

- Commit `.env` or any file containing real API keys.
- Infer regulatory approval status from paper text.
- Return extracted values without an accompanying evidence snippet.
- Silently drop missing metrics — mark them explicitly as `None` or `"missing"`.
- Add `print()` statements — use `loguru`.
- Break existing tests without explicit user approval.
- Add dependencies without updating `requirements.txt`.
- Produce a final ranking using only LLM output — always use a deterministic scoring function.
- Parse LLM responses as raw text — always validate against a Pydantic model.
- Add a major component without updating `DEVELOPER_NOTES.md`.
