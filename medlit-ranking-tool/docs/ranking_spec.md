# MedLit Ranking Tool — Ranking Specification

## 1. Principles

1. **Target-relative** — ranking is computed relative to the user-supplied target product profile and desired comparison metrics. A paper is not ranked in the abstract; it is ranked against what the user is looking for.
2. **Deterministic** — given identical extracted fields and an identical search request, the composite score must be identical across runs.
3. **Transparent** — every dimension score, the weights used, and any incompleteness flags are stored and returned so analysts can audit rankings end-to-end.
4. **LLM as signal, not arbiter** — LLM output (e.g. study-design label, topical relevance label) is converted to a numeric value by a module-level lookup table in Python. The LLM never emits a raw score, and lookup tables are never loaded from prompts or config.
5. **Graceful degradation** — if a dimension cannot be scored because the required input is absent (no target profile, no target metrics, missing extracted field), it is excluded entirely and the remaining weights are renormalised. Arbitrary neutral defaults are not used.

---

## 2. Scoring Dimensions

### 2.1 Relevance Score  `R ∈ [0, 1]`

Measures how closely the paper matches the user's **search intent** — the query terms, MeSH headings, and free-text keywords supplied in the search request — plus **publication recency** relative to the scoring date. Relevance is one dimension of the composite; a high relevance score alone does not make a paper rank first.

| Sub-signal | Method | Weight within R |
|---|---|---|
| Title keyword overlap | Recall of query tokens found in title | 0.25 |
| Abstract keyword overlap | Recall of query tokens found in abstract | 0.25 |
| MeSH / keyword match | Exact match count ÷ total query MeSH terms | 0.25 |
| LLM topical relevance label | Lookup: `high→1.0`, `medium→0.5`, `low→0.0` | 0.15 |
| Publication recency | Tiered score from `published_date` (see below) | 0.10 |

**Recency tiers** (years since publication, using calendar span ÷ 365.25): ≤ 2 y → 1.0; ≤ 5 y → 0.7; ≤ 10 y → 0.4; \> 10 y → 0.1. Missing `published_date` scores 0.0 for this sub-signal.

If the search request contains no keywords or MeSH terms, the sub-signals that depend on them are excluded and their weights are redistributed within R. Recency is always included when a `Paper` is present.

---

### 2.2 Product Similarity Score  `P ∈ [0, 1]`

Measures how closely the device or drug described in the paper matches the **user-supplied target product profile**. Scoring operates on **normalized canonical values** produced by the ophthalmology normalization layer — never on raw strings.

`TargetProductProfile.target_type` controls which sub-signals are active: `"device"`, `"drug"`, or `"both"`.

#### Device sub-signals

String fields use **two-tier matching**: exact case-insensitive match → 1.0; one string contained in the other → 0.6; else 0.0 (except where noted).

| Sub-signal | Method | Default weight |
|---|---|---|
| Intended use | Two-tier match on normalized intended use | 0.15 |
| Device category | Two-tier match on canonical category | 0.15 |
| Material subtype | Exact subtype → 1.0; same family → 0.5; else 0.0 | 0.12 |
| Indications | Jaccard over canonical indication sets | 0.12 |
| Energy source | Two-tier match on normalized energy modality | 0.05 |
| Anatomical site | Two-tier match on canonical site | 0.08 |
| Device class | Exact match on `class_i` / `class_ii` / `class_iii` → 1.0; else 0.0 | 0.03 |
| Product name | Normalised Levenshtein on raw product name | 0.10 |
| Key features | Jaccard over normalized feature tag sets | 0.05 |
| Manufacturer | Two-tier match on raw manufacturer | 0.05 |
| Sterilization | Two-tier match on normalized sterilization method | 0.03 |
| Material features | Jaccard over normalized feature tag sets | 0.05 |

Default weights are **relative**; only sub-signals with both target and extracted values present are activated, and those weights renormalize to 1.0 within **P**. When a **submission type preset** is selected (see §2.5), device (and drug) sub-signal weights are overridden from the preset and merged with defaults for any keys omitted from the preset.

#### Drug sub-signals

| Sub-signal | Method | Weight |
|---|---|---|
| Active ingredient | Exact canonical match → 1.0; else 0.0 | 0.30 |
| Drug class | Exact canonical class match → 1.0; else 0.0 | 0.15 |
| Indications | Jaccard over canonical indication sets | 0.15 |
| Route | Exact canonical match → 1.0; else 0.0 | 0.10 |
| Formulation features | Jaccard over normalized feature tags | 0.05 |
| Product name | Normalised Levenshtein on raw product name | 0.05 |

#### Normalization and confidence

- Device material is normalized by `app.normalization.materials` with two confidence tiers: direct material descriptions (0.95) and brand/trade name hints (0.60). Brand hints are only used when no direct material description is found.
- Drug active ingredients are normalized by `app.normalization.drugs` (confidence 0.95 for known INN/brand entries).
- Normalization happens **once** after extraction and is stored in a `NormalizedProduct` object. The scorer receives this object directly and never calls normalization functions.

**Scoring rules:**

- Only sub-signals for which both the target profile field and the extracted (normalized) paper field are non-null are evaluated. The rest are excluded and their weights redistributed within P.
- If the target product profile is not supplied at all, `P` is excluded from the composite and its weight is redistributed across remaining dimensions.
- For `target_type="both"`, device sub-signals receive 55 % of P weight and drug sub-signals receive 45 %.

---

### 2.3 Metric Favorability Score  `M ∈ [0, 1]`

Measures how favourable the paper's reported outcome metrics are relative to the **user-supplied target metrics** — each of which carries a direction rule and an optional threshold or reference value.

#### Direction rules

Each target metric must declare one of the following comparison modes:

| Mode | Meaning | Formula |
|---|---|---|
| `higher_better` | Higher values are more favourable | `clip((value - threshold) / range, 0, 1)` |
| `lower_better` | Lower values are more favourable | `clip((threshold - value) / range, 0, 1)` |
| `range_best` | Value within `[lo, hi]` is fully favourable; outside is penalised linearly | `1.0` if `lo ≤ value ≤ hi`; else `clip(1 - dist / range, 0, 1)` |
| `closer_better` | Closer to a target value is more favourable | `clip(1 - abs(value - target) / range, 0, 1)` |

`range` is the normalisation span supplied with the target metric (e.g. plausible physiological range). It must be > 0; if not supplied, the dimension for that metric is excluded.

#### Aggregation

```
M = mean(favorability_i)   over all matched, scoreable metrics
```

#### Missing-metric handling

- If a target metric is not found in the paper's extraction output, that metric is **excluded** from the mean — it does not count as favourable or unfavourable.
- If **no** target metrics are supplied, `M` is excluded from the composite entirely and its weight is redistributed.
- If target metrics are supplied but **none** appear in any paper, `M` is scored as 0.0 and `metric_score_incomplete: true` is flagged on every result.
- `metric_score_estimated` is set to `true` whenever fewer than all target metrics were matched for a given paper.

---

### 2.4 Evidence Quality Score  `E ∈ [0, 1]`

Maps study design, sample size, follow-up duration, and comparator type to a quality tier aligned with an **FDA/CDRH-style** hierarchy for ophthalmology evidence. The study design label comes from LLM extraction (controlled vocabulary) and is converted to a base score by a Python lookup table — the LLM does not emit the score itself.

**Study design base scores:**

| Study type (LLM label) | Base score |
|---|---|
| `systematic_review` / `meta_analysis` | 1.00 |
| `rct` | 0.90 |
| `prospective_cohort` | 0.70 |
| `retrospective_cohort` | 0.50 |
| `case_control` | 0.40 |
| `case_series` | 0.30 |
| `case_report` | 0.15 |
| `bench_study` | 0.15 |
| `in_vitro_study` | 0.15 |
| `animal_study` | 0.20 |
| `narrative_review` | 0.15 |
| `unknown` | 0.20 |

**Sample size modifier** (ophthalmology-oriented tiers; additive, combined result clipped to [0, 1]):

| n (participants / eyes) | Modifier |
|---|---|
| ≥ 500 | +0.10 |
| 300 – 499 | +0.08 |
| 100 – 299 | +0.05 |
| 30 – 99 | +0.02 |
| 10 – 29 | 0.00 |
| < 10 | −0.05 |

**Follow-up modifier** (from optional numeric `follow_up_months` on extraction):

| Follow-up (months) | Modifier |
|---|---|
| ≥ 24 | +0.08 |
| ≥ 12 | +0.05 |
| ≥ 6 | +0.02 |
| \< 6 or missing | 0.00 |

**Comparator modifier** (from optional `comparator_type` on extraction):

| Comparator | Modifier |
|---|---|
| `active` | +0.05 |
| `sham` / `placebo` | +0.03 |
| `historical` | +0.01 |
| `none` / `unknown` / missing | 0.00 |

```
E = clip(base_score + size_modifier + follow_up_modifier + comparator_modifier, 0, 1)
```

**Evidence domain cap:** The extraction output includes an `evidence_domain` field (`human_clinical`, `animal`, `in_vitro`, `bench`, `mixed`, `unknown`). When present, the scorer applies a downward cap after the formula above:

| `evidence_domain` | Cap |
|---|---|
| `human_clinical` | *(no cap)* |
| `animal` | 0.60 |
| `in_vitro` / `bench` | 0.40 |
| `mixed` | 0.50 |
| `unknown` | *(no cap)* |

If the study design label is `unknown` and sample size is missing, `evidence_score_estimated: true` is flagged.

---

### 2.5 Submission type presets

The search request may include `submission_type`: `510k`, `pma`, or `de_novo`. When set **and** custom composite `weights` are not supplied, **composite** dimension weights (R / P / M / E) are filled from the corresponding preset. **Product Similarity** sub-signal weights for device and drug paths are also taken from the same preset (merged with code defaults so omitted keys keep default relative weights).

| Preset | R | P | M | E |
|---|---|---|---|---|
| `510k` | 0.20 | 0.40 | 0.20 | 0.20 |
| `pma` | 0.15 | 0.20 | 0.30 | 0.35 |
| `de_novo` | 0.20 | 0.30 | 0.20 | 0.30 |

**510(k)** emphasizes product match (especially intended use in the device sub-weight table). **PMA** emphasizes evidence quality and metric favorability. **De Novo** is balanced between product and evidence.

Device sub-weights per preset (each row sums to 1.0 among listed keys; see implementation `SUBMISSION_PRESETS` for exact numbers): intended use, device category, material subtype, indications, energy source, anatomical site, device class, product name, key features, manufacturer, sterilization — tuned per pathway.

---

## 3. Composite Score

```
C = w_R·R + w_P·P + w_M·M + w_E·E
```

**Default weights:**

| Dimension | Symbol | Default weight |
|---|---|---|
| Relevance | R | 0.35 |
| Product similarity | P | 0.25 |
| Metric favorability | M | 0.20 |
| Evidence quality | E | 0.20 |

Weights must sum to 1.0. When one or more dimensions are excluded due to missing inputs, the remaining active weights are renormalised before scoring:

```
w_i_active = w_i / sum(w_j for j in active_dimensions)
```

Custom weights may be supplied per search request (API-validated: must sum to 1.0 ± 0.001 and all values must be ≥ 0).

**Submission type:** If `submission_type` is set and `weights` is omitted, composite weights are assigned from the preset in §2.5. If explicit `weights` are provided, they take precedence.

**Similarity threshold:** Optional `similarity_threshold` ∈ [0, 1] on the search request drops any paper whose **composite** score is **strictly below** this value before ranking. If omitted, no threshold filtering is applied.

---

## 4. Ranking Output

When `similarity_threshold` is set, papers below it are excluded **before** sorting. Remaining papers are sorted by `composite_score` descending. Ties are broken by `evidence_quality_score` descending, then `published_date` descending (most recent first).

Each `RankedPaper` in the response includes:

```jsonc
{
  "rank": 1,
  "composite_score": 0.812,
  "relevance_score": 0.91,
  "product_similarity_score": 0.74,
  "metric_favorability_score": 0.80,
  "evidence_quality_score": 0.85,
  "weights_used": { "R": 0.35, "P": 0.25, "M": 0.20, "E": 0.20 },
  "dimensions_excluded": [],
  "metric_score_estimated": false,
  "metric_score_incomplete": false,
  "evidence_score_estimated": false,
  "ranking_rationale": "High relevance to query terms; strong product match on device category and indication; MACE rate below target threshold; RCT with n=512.",
  "submission_type": "510k"
}
```

`submission_type` echoes the request’s submission pathway when set; otherwise `null`.

**Field notes:**

| Field | Description |
|---|---|
| `dimensions_excluded` | List of dimension symbols (`"P"`, `"M"`) excluded due to missing inputs; weights were renormalised. |
| `metric_score_estimated` | `true` if fewer than all target metrics were matched in this paper. |
| `metric_score_incomplete` | `true` if no target metrics appeared in the paper at all; `M` scored 0.0. |
| `evidence_score_estimated` | `true` if study design was `unknown` and sample size was missing. |
| `ranking_rationale` | Short plain-text string (generated deterministically from the top contributing sub-signals) explaining why the paper ranked where it did. Not LLM-generated at runtime. |

---

## 5. Implementation Notes

- All scoring functions live in `app/ranking/` as pure functions: `score_relevance`, `score_product_similarity`, `score_metric_favorability`, `score_evidence_quality`, `score_composite`.
- Each function signature follows `score_*(extracted: ExtractionResult, query: SearchQuery) -> tuple[float, dict]` — returning both the score and a sub-signal breakdown for auditability.
- The composite scorer in `app/ranking/composite.py` handles weight renormalisation, flag aggregation, and rationale assembly.
- Unit tests for every scoring function are required in `tests/ranking/`, including cases for missing fields, all direction modes, and weight renormalisation.
- LLM label → numeric value lookup tables (study design, topical relevance) are defined as module-level `dict` constants — never loaded from config, environment, or prompts.
- Regulatory approval status is never used as a scoring signal.
