# Overnight scoring overhaul — FDA-style ophthalmology evidence

This document summarizes the **FDA-style ophthalmology evidence scoring** and **relevance recency** changes applied to the MedLit ranking pipeline, with rationale and representative score shifts.

## Goals

1. Align **Evidence Quality (`E`)** with FDA/CDRH expectations: stronger weight on RCTs, pivotal-scale samples, adequate follow-up, and active comparators.
2. Add a **publication recency** sub-signal to **Relevance (`R`)** so newer human clinical evidence is preferred when other signals are similar.
3. Keep scoring **deterministic** and **auditable** (lookup tables + modifiers in Python, not LLM-emitted floats).

## Code and schema changes

| Area | Change |
|------|--------|
| `app/models/extraction.py` | New optional `follow_up_months` (`EvidenceInt \| None`). New optional `comparator_type` (`ComparatorType` enum). New enum: `active`, `sham`, `placebo`, `historical`, `none`, `unknown`. |
| `docs/extraction_schema.json` | Documented `follow_up_months` and `comparator_type` on `study`. |
| `app/ranking/evidence_quality.py` | Recalibrated base scores; ophthalmology sample tiers; follow-up and comparator modifiers; `E = clip(base + size + follow_up + comparator)` then domain cap. |
| `app/ranking/relevance.py` | Weights: title 0.25, abstract 0.25, mesh 0.25, topical 0.15, **recency 0.10**. Recency tiers from `Paper.published_date` (optional `reference_date` for tests). |
| `docs/ranking_spec.md` | §§2.1 and 2.4 updated to match implementation. |

## FDA / clinical rationale

- **RCT and prospective designs** are elevated relative to observational work to mirror regulatory acceptance of interventional evidence for safety and effectiveness claims.
- **Sample tiers** at 300–500+ reflect common pivotal-scale eye counts in ophthalmic device/drug programs (vs generic 10/100/1000 thresholds).
- **Follow-up** (6 / 12 / 24 months) reflects typical primary-endpoint horizons for IOL and retinal therapies.
- **Comparator quality** rewards head-to-head and placebo/sham control over single-arm or historical comparisons.
- **Recency** in `R` reflects regulatory and clinical practice preference for up-to-date evidence without changing the `E` dimension’s definition of study quality.

## Evidence Quality — before / after (representative)

Values are **illustrative** for the same extracted labels before modifiers were expanded; actual `E` depends on domain caps and all modifiers.

| Study context | Before (approx.) | After (approx.) | Notes |
|---------------|------------------|-----------------|-------|
| RCT, human, n=300 | Base 0.85 + size +0.05 → 0.90 | Base 0.90 + size +0.08 → 0.98 → clip 1.0 | Stronger RCT base + pivotal tier |
| Prospective cohort, n=250 | Base 0.70 + size +0.05 → 0.75 | Base 0.70 + size +0.08 → 0.78 | Cohort base is 0.70; size tiers are discrete |
| Case series, n=80 | Base 0.25 + size 0 → 0.25 | Base 0.30 + size +0.02 → 0.32 | Design floor + small-sample tier |
| Unknown design, no n | Base 0.05 | Base 0.20 | Higher floor; still flagged `evidence_score_estimated` when type unknown and n missing |

## Relevance — recency tiers

| Years since publication | Recency sub-signal |
|-------------------------|-------------------|
| ≤ 2 | 1.0 |
| ≤ 5 | 0.7 |
| ≤ 10 | 0.4 |
| \> 10 | 0.1 |
| Missing date | 0.0 |

## Demo benchmark (design intent)

For the acrylic IOL search payload, **DEMO001** (hydrophobic acrylic, prospective cohort, n=250, newer publication) should remain **above** **DEMO004** (silicone, case series, n=80, older publication) on composite score due to higher **P** (material match), **E**, and **R** (including recency and topical label). Run:

```bash
pytest tests/ranking/ tests/integration/test_search.py tests/integration/test_demo_mode.py tests/integration/test_smoke.py -v
```

to confirm in your environment.

**Note:** Integration tests force `APP_MODE=demo` by mutating `app.core.config.settings.APP_MODE` before importing the FastAPI app (see `tests/integration/conftest.py`), because `.env` can set `APP_MODE=live` with higher precedence than `os.environ`.
