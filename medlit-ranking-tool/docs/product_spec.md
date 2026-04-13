# MedLit Ranking Tool — Product Specification

## 1. Purpose

MedLit Ranking Tool is an internal research-support service that automates the discovery, extraction, and prioritisation of medical device literature. It helps clinical, regulatory, and market-access teams quickly surface the most relevant published evidence without manual triage.

---

> **Development Note:** Implementation and code generation for this project may be assisted by [Cursor](https://cursor.sh/) using Claude Opus. This is a development-time tooling choice and is entirely separate from the application runtime. The application itself uses **Qwen (via DashScope)** as its default runtime model for structured field extraction, configurable via `LLM_MODEL` and `LLM_BASE_URL` to swap providers (e.g. OpenAI GPT-4o).

---

## 2. Users

| Persona | Need |
|---|---|
| **Clinical / regulatory analyst** | Ranked reading list for a specific device category or outcome metric |
| **Market-access researcher** | Comparative evidence across competitor products |
| **R&D scientist** | Novel findings and evidence gaps in a therapeutic area |

---

## 3. Goals and Non-Goals

### Goals
- Ingest papers from PubMed (and future sources: CrossRef, Semantic Scholar).
- Extract structured device, metric, and outcome data from titles and abstracts using a configurable runtime LLM.
- Rank papers relative to a user-supplied target product profile and desired comparison metrics using a deterministic composite score derived from relevance, product similarity, metric favorability, and evidence quality.
- Expose results via a versioned REST API.
- Provide a machine-readable extraction payload (JSON) for downstream integrations.

### Non-Goals
- This tool does **not** determine or imply regulatory approval status.
- It does **not** replace expert clinical review.
- It does **not** provide patient-facing outputs.

---

## 4. Features

### 4.1 Ingestion
- Query PubMed via the NCBI E-utilities API using MeSH terms, free text, or DOI.
- Paginate and de-duplicate results by PMID / DOI.
- Store raw paper metadata in the database for reproducibility.

### 4.2 Extraction
- Parse titles and abstracts (full-text PDF ingestion is out of scope for MVP).
- Call the runtime LLM — **Qwen via DashScope by default**, configurable via `LLM_MODEL` and `LLM_BASE_URL` — to populate the structured fields defined in `extraction_schema.json`.
- Every extracted value **must** be accompanied by an evidence snippet: a verbatim quote from the source text that supports the value.
- Fields that cannot be determined are set to `null` — never silently omitted or guessed.
- Both `device` and `drug` sections are **optional**: the LLM sets whichever is applicable (device, drug, both, or neither). Empty fabricated sections are never accepted.

### 4.2.1 Normalization
- After LLM extraction, raw strings are passed through the **ophthalmology normalization layer** (`app/normalization/`).
- The normalization layer maps noisy text to canonical ophthalmology vocabularies: device categories, IOL materials (with brand/direct alias confidence distinction), drug active ingredients, drug classes, anatomical sites, and indications.
- Normalization is **deterministic and dictionary/rule-based** — no LLM calls are made during normalization.
- Normalized outputs are stored as `NormalizedProduct` objects and passed directly to the scorer; normalization never happens inside the scoring functions.
- If normalization confidence is below threshold (e.g. brand hints yield 0.60 vs. direct aliases at 0.95), the normalized field is still used but contributes only to scoreable sub-signals when both target and extracted values are non-null.

### 4.3 Ranking

**Live search pipeline (two phases):** Before full structured extraction, the service fetches a **pool** of PubMed hits (`pool_size`, default 100, configurable). A lightweight **AI triage** step reads only titles and abstracts and selects the top `max_results` papers (e.g. 5–50) for relevance to the query and target product profile. The streaming search API emits the pool in batches via **`pool`** events, then **`accept`** events as each shortlisted PMID is produced (line-by-line streaming); a **`status`** with `phase: "extracting"` signals triage is complete. Full LLM extraction, normalization, and composite scoring run **only** on that shortlist, reducing cost and noise from irrelevant PubMed matches.

- In **live** mode, the **relevance (R)** dimension uses a dedicated LLM call (blended with deterministic publication recency); product similarity (P), metric favorability (M), and evidence quality (E) remain **deterministic** from extracted fields. **Demo** mode uses fully deterministic relevance for fixtures and offline tests.
- Score each paper across four dimensions relative to the **user-supplied target product profile and desired comparison metrics**; see `ranking_spec.md` for formulas and weights.
- Optional **FDA submission pathway** (`510k`, `pma`, `de_novo`) selects preset composite weights and product-similarity sub-weights when custom weights are not provided; see `ranking_spec.md` §2.5.
- Optional **similarity threshold** filters out papers whose composite score is below the cutoff before ordering.
- **P / M / E** are deterministic given the same extracted fields. **R** (live) additionally uses an LLM semantic score blended with recency; triage and extraction still use the LLM only for selection and structured extraction, not for P/M/E.
- Results are returned as an ordered `RankedPaper` list with per-dimension scores exposed for full auditability.

### 4.4 API
All endpoints are under `/api/v1/`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/search` | Submit a search query; returns a job ID |
| `GET` | `/search/{job_id}` | Poll job status and retrieve results |
| `GET` | `/papers/{pmid}` | Fetch stored paper by PMID |
| `POST` | `/papers/{pmid}/extract` | (Re-)run extraction on a stored paper |
| `GET` | `/papers/{pmid}/ranking` | Retrieve ranking scores for a paper |
| `GET` | `/health` | Liveness check |

### 4.5 Storage
- SQLite in development (`data/medlit.db`); configurable via `DATABASE_URL` for PostgreSQL in production.
- Raw paper metadata and extraction payloads are persisted per search session.

---

## 5. Configuration

All runtime settings are loaded from environment variables (`.env`). See `.env.example` for the full list. Key settings:

| Variable | Purpose | Default |
|---|---|---|
| `LLM_API_KEY` | API key for the runtime extraction LLM | *(required)* |
| `LLM_MODEL` | Model name for extraction | `qwen-plus` |
| `LLM_BASE_URL` | OpenAI-compatible base URL (leave empty for OpenAI native) | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `NCBI_API_KEY` | PubMed rate limit increase | *(optional)* |
| `NCBI_EMAIL` | NCBI fair-use requirement | *(optional)* |
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///./data/medlit.db` |
| `LOG_LEVEL` | Loguru log level | `INFO` |

---

## 6. Quality and Safety Constraints

- Regulatory approval status must **never** be inferred from paper text.
- Extracted values without an evidence snippet must be rejected at the service layer.
- All LLM responses are validated against `extraction_schema.json` before persistence; malformed responses raise a structured error — they are never silently accepted.
- No secrets are committed to version control.

---

## 7. Out-of-Scope for MVP

- Full-text PDF ingestion (abstracts only in v1).
- User authentication / multi-tenancy.
- Front-end UI.
- Scheduled / background ingestion jobs.
