# AGENTS.md

This project is a Python MVP for a medical-device literature intelligence tool.

## Goals

- Search biomedical literature
- Extract device/product details and numeric outcomes
- Generate paper synopsis
- Rank papers by relevance, product similarity, metric favorability, and evidence quality

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
- **Config**: All settings via `app.core.config.Settings` (pydantic-settings). Never hardcode secrets.
- **Logging**: Use `loguru` logger, never `print()`.
- **Tests**: Pytest. New features must include tests. Place tests in `tests/` mirroring the `app/` structure.

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `app/api/` | FastAPI routers and request/response schemas |
| `app/core/` | Config, logging, shared helpers |
| `app/models/` | Pydantic domain models (Paper, ExtractedMetric, RankedPaper, …) |
| `app/services/` | Orchestration and business logic |
| `app/ingestion/` | Fetching papers from external sources (PubMed, CrossRef, etc.) |
| `app/extraction/` | PDF parsing, field extraction, LLM prompting, evidence linking |
| `app/ranking/` | Scoring algorithms: relevance, similarity, metric favorability, evidence quality |

## Do Not

- Commit `.env` or any file containing real API keys.
- Infer regulatory approval status from paper text.
- Return extracted values without an accompanying evidence snippet.
- Silently drop missing metrics — mark them explicitly as `None` or `"missing"`.
- Add `print()` statements — use `loguru`.
- Break existing tests without explicit user approval.
- Add dependencies without updating `requirements.txt`.
