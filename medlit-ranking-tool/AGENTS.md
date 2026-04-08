# AGENTS.md — AI Agent Guidelines

This file provides instructions for AI coding agents (Cursor, Copilot, Claude, etc.) working in this repository.

## Project Purpose

MedLit Ranking Tool is a Python/FastAPI application that ingests medical literature, extracts structured data, and ranks papers for researchers. Correctness, traceability, and reproducibility are paramount.

## Code Conventions

- **Language**: Python 3.11+, fully type-annotated (`from __future__ import annotations` not required; use built-in generics).
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
| `app/models/` | Pydantic domain models |
| `app/services/` | Orchestration and business logic |
| `app/ingestion/` | Fetching papers from external sources (PubMed, CrossRef, etc.) |
| `app/extraction/` | PDF parsing, field extraction, LLM prompting |
| `app/ranking/` | Scoring algorithms and ranking pipeline |

## Do Not

- Commit `.env` or any file containing real API keys.
- Add `print()` statements — use `loguru`.
- Break existing tests without explicit user approval.
- Add dependencies without updating `requirements.txt`.
