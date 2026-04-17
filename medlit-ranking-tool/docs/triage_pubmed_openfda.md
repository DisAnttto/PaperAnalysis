# How Triage Works: Split-Track Architecture (Literature vs Regulatory)

This document describes how the hybrid triage pipeline treats literature (PubMed) and regulatory (openFDA, ClinicalTrials.gov, DailyMed, AccessGUDID) records. It reflects the **split-track** implementation in `app/services/triage.py` and `app/models/paper.py`.

---

## 1. Purpose

Triage takes a **mixed pool** of `Paper` objects and returns up to **`top_n` UIDs**. Two **independent tracks** evaluate papers on their own terms:

| Track | Sources | Why separate |
|-------|---------|--------------|
| **Literature** | PubMed (and any unlisted source) | Has abstract, MeSH, clinical-study text |
| **Regulatory** | openFDA, ClinicalTrials, DailyMed, AccessGUDID | Typically lacks abstract/MeSH; value comes from product identity and regulatory alignment |

The same logic runs for **batch** (`triage_papers`) and **streaming** (`triage_papers_stream`).

---

## 2. Identity: UID

Each `Paper` has a **`uid`** property used everywhere:

- **PubMed:** `uid` = PMID (`paper.pmid`)
- **openFDA:** `uid` = K-number or application number (`paper.identifier`)
- **ClinicalTrials:** `uid` = NCT ID (`paper.identifier`)
- **DailyMed / AccessGUDID:** `uid` = source-specific ID (`paper.identifier`)
- **Fallback:** SHA-256 of the title (truncated to 16 hex chars, stable across restarts)

---

## 3. Slot Allocation

When both tracks have papers, slots are split via `_allocate_slots`:

- **70 %** of `top_n` → Literature track
- **30 %** of `top_n` → Regulatory track (`_REGULATORY_SLOT_FRACTION = 0.30`)

If one track has fewer papers than its allocation, surplus slots spill over to the other track via a **deficit backfill** mechanism (an extra triage pass runs on the other track to fill remaining slots).

Both tracks are guaranteed at least **one slot** when they have papers.

---

## 4. Phase 1 — Deterministic Pre-Score

### Literature track (`prescore_paper`)

Weighted sum of four signals in **[0, 1]**:

| Signal | Weight | Measures |
|--------|--------|----------|
| `query_title` | 0.25 | Fraction of query tokens appearing in **title** |
| `query_abstract` | 0.20 | Same recall over **abstract** tokens |
| `profile_signal` | 0.40 | Target product profile match (drug/device name in title/abstract + indication bonus) |
| `mesh_overlap` | 0.15 | Profile terms found in **MeSH headings** |

### Regulatory track (`prescore_regulatory`)

Renormalized weights that **do not penalize** absent abstract/MeSH:

| Signal | Weight | Measures |
|--------|--------|----------|
| `query_title` | 0.35 | Query-token recall in title |
| `profile_signal` | 0.55 | Product/device/drug name and indication match |
| `identifier_match` | 0.10 | Exact product number or K-number in query/profile |

Regulatory records are scored only on fields they **actually have**, so a 510(k) clearance with no abstract is not penalized for lacking one.

---

## 5. Anchor Detection

**Anchors** are papers whose **title** contains a target drug/device name (`active_ingredient` or `product_name`, case-insensitive substring).

- Anchors are detected on the **literature track only**
- Anchored UIDs get a **combined score floor** of 0.5 (`_ANCHOR_FLOOR`)
- They are **guaranteed placement** in the final selection before generic fill
- Anchor selection is **capped at `top_n`** so anchors cannot consume all slots

---

## 6. Phase 2 — LLM Relevance Scoring

Each track has its **own LLM system prompt**:

### Literature prompt (`_TRIAGE_SYSTEM`)
Instructs the LLM to score clinical/research papers on relevance to the query and product. Emphasis on study quality, population match, and outcome reporting.

### Regulatory prompt (`_REGULATORY_TRIAGE_SYSTEM`)
Instructs the LLM to score regulatory/product records on product identity match, regulatory alignment, and submission relevance. Does **not** expect or penalize for missing clinical study abstracts.

**Shortlist construction** (per track):
- All anchor UIDs (literature track)
- Top pre-scored papers up to `shortlist_size = min(pool, max(top_n * 2, anchors + top_n))`
- LLM only runs if `len(shortlist) > top_n`

**LLM output format:** `UID<TAB>SCORE` (0-10, normalized to [0, 1]).

---

## 7. Combined Score

Per paper:

- **With LLM score:** `combined = 0.35 * pre_score + 0.65 * llm_score`
- **Without LLM score:** `combined = pre_score`
- **If anchor (literature):** `combined = max(combined, 0.5)`

---

## 8. Phase 3 — Final Selection (`_combine_and_select`)

Within each track, papers are sorted by `combined` descending, then UIDs selected:

1. **Anchors first** (literature track only, capped at track's slot count)
2. **Fill remaining slots** by highest combined score

After both tracks select their papers, results are **merged** and returned as a single list up to `top_n`.

---

## 9. Special Cases

| Situation | Behavior |
|-----------|----------|
| `len(pool) <= top_n` | No triage competition — every UID returned |
| Shortlist <= track slots | No LLM call for that track; order by pre-score |
| No target profile | `profile_signal`, `mesh_overlap`, `identifier_match` all zero; pre-score relies on query-title and query-abstract only |
| Only one track has papers | That track gets all `top_n` slots |
| LLM call fails | `combined = pre_score` (plus anchor floor if applicable) |

---

## 10. Summary: Literature vs Regulatory in Triage

| Aspect | Literature (PubMed) | Regulatory (openFDA, CT, DailyMed, GUDID) |
|--------|--------------------|--------------------------------------------|
| **Pre-score** | 4 signals (title, abstract, profile, MeSH) | 3 signals (title, profile, identifier) |
| **Missing-field penalty** | Possible (low abstract/MeSH → lower score) | None (weights renormalized to available fields) |
| **LLM prompt** | Clinical evidence focus | Product identity / regulatory focus |
| **Anchors** | Yes — floor + guaranteed slots | No anchors (product identity in pre-score) |
| **Slot allocation** | ~70 % of `top_n` | ~30 % of `top_n` |
| **Deficit handling** | Absorbs surplus regulatory slots | Absorbs surplus literature slots |

---

## References

- Implementation: `app/services/triage.py` — `prescore_paper`, `prescore_regulatory`, `detect_anchors`, `_allocate_slots`, `_combine_and_select`, `triage_papers`, `triage_papers_stream`
- Identity: `app/models/paper.py` — `Paper.uid`, `Paper.source`
- Constants: `_PRE_WEIGHTS`, `_REGULATORY_PRE_WEIGHTS`, `_REGULATORY_SOURCES`, `_REGULATORY_SLOT_FRACTION`
