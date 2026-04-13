# How Triage Works: PubMed vs openFDA

This document describes how the hybrid triage pipeline treats PubMed literature versus openFDA (and other non-PubMed) records. It reflects the implementation in `app/services/triage.py` and `app/models/paper.py`.

## 1. Purpose

Triage takes a **mixed pool** of `Paper` objects (from PubMed, openFDA, ClinicalTrials.gov, DailyMed, AccessGUDID, etc.) and returns up to **`top_n` UIDs** (usually `max_results` in the search API). The same logic runs for **batch** (`triage_papers`) and **streaming** (`triage_papers_stream`) search, except streaming uses a streaming LLM call and then the same final selection step.

There is **no separate "PubMed triage" vs "openFDA triage"** algorithm. Every item uses the same formulas and selection rules. Differences come from **what fields each source fills** (PMID, abstract, MeSH, title shape) and from **source-specific guarantees** (non-PubMed diversity).

## 2. Identity: UID, not "PMID only"

Each `Paper` has a **`uid`** used everywhere in triage:

- **PubMed:** `uid` is normally the **PMID** (`paper.pmid`).
- **openFDA (510(k)):** `uid` is the **K-number** (stored in `paper.identifier`; `pmid` is unset).

So the LLM is asked to score lines like `ID=39350227` vs `ID=K123456`, not "PMID only."

## 3. Phase 1 — Deterministic pre-score (same for all sources)

Every valid paper gets **`prescore_paper(paper, query, target_product)`** in **[0, 1]**. It is a weighted sum of four signals:

| Signal | Weight | What it measures |
|--------|--------|------------------|
| **query_title** | 0.25 | Fraction of query tokens (length > 2, lowercased) that appear in the **title** |
| **query_abstract** | 0.20 | Same recall over **abstract** tokens |
| **profile_signal** | 0.40 | Match of **target product profile** (names, indications, intended use, drug class, etc.) to title/abstract |
| **mesh_overlap** | 0.15 | How many profile terms appear in **MeSH headings** |

### PubMed papers

- Usually have **abstract** and often **MeSH** → can score on all four channels.
- **Profile signal** can be strong if the title/abstract mention the drug/device/indication from the sidebar.

### openFDA 510(k) papers (as ingested in the pool)

- **Title** is typically like `510(k) K…: <device name>` — can still match **query_title** and **profile_signal** if the query/profile align with device names or terms.
- **Abstract** is often empty or short (only if `statement_or_summary` was present) → **query_abstract** is often **0**.
- **MeSH** is empty → **mesh_overlap** is **0**.

So openFDA rows can be at a **structural disadvantage** on pre-score (up to **35%** of the weight may be "unavailable"), even when they are useful for a submission. That is why later steps add **LLM shortlist inclusion** and **source-diversity** in the final pick (see below).

## 4. Anchor detection (PubMed and openFDA)

**Anchors** are papers whose **title** contains a **target name** from the profile: `active_ingredient` and/or `product_name` (case-insensitive substring).

- Applies to **any** `Paper` with a title, including openFDA.
- If the 510(k) title contains e.g. "faricimab" and the profile names faricimab, that row can be an anchor.
- **Anchors are not PubMed-specific.**

Anchored UIDs get:

- **`combined` score floor:** after blending pre + LLM, `combined` is at least **0.5** (`_ANCHOR_FLOOR`).
- **Guaranteed placement** in the final list **before** generic top-by-score fill (see Phase 3).

## 5. LLM shortlist (who gets an LLM score)

When the pool is larger than `top_n`, the code does **not** send every paper to the LLM. It builds a **shortlist** with a capped size:

`shortlist_size = min(pool_size, max(top_n * 2, num_anchors + top_n))`

Then it fills `shortlist_uids` in this order:

1. **All anchor UIDs** (always included).
2. **Best pre-scored paper per non-PubMed source** — for each `source != "PubMed"`, the **first** paper in **pre-score descending order** for that source is forced in. That way at least one **openFDA** (and one ClinicalTrials, etc.) candidate is in the prompt even if pre-score is low.
3. **Top pre-scored papers** (any source) until the shortlist reaches `shortlist_size`.

**PubMed** items compete on pre-score for slots in step 3; they are not given a separate "best per source" slot because PubMed is the default bulk literature source.

**When LLM scoring runs:** only if `len(shortlist_papers) > top_n`. If the shortlist is small (e.g. pool barely above `top_n`), the LLM may be skipped and everyone relies on pre-score only for the blend (and items outside the shortlist have **no** `llm_score`).

## 6. Phase 2 — LLM relevance scoring

The model receives:

- The **search query**
- A text summary of the **target product profile**
- One line per shortlist item:  
  `[index] ID=<uid> | SOURCE=<PubMed|openFDA|…> | <title> | <truncated abstract>`

The **system prompt** states that items come from **multiple databases** (PubMed, openFDA, ClinicalTrials, DailyMed, AccessGUDID) and that **regulatory/product records** should be scored on **relevance to the query/product**, not on having a clinical-study abstract.

The model must output one line per item: **`ID` + tab + score 0–10** (parsed and normalized to **[0, 1]**).

**Parsing** only keeps scores whose ID is in the shortlist's allowed set. Typos or wrong IDs are dropped for that row.

**If the LLM call fails:** all `llm_scores` stay empty → **combined = pre_score** only (plus anchor floor for anchors).

## 7. Combined score (per paper)

For each paper in the **full valid pool** (not only the shortlist):

- **`pre_score`:** from Phase 1.
- **`llm_score`:** from Phase 2 **if** that UID was in the shortlist **and** the parser accepted a line; else **`None`**.

**Combined:**

- If `llm_score` is not `None`:  
  `combined = 0.35 * pre_score + 0.65 * llm_score`
- If `llm_score` is `None`:  
  `combined = pre_score`

Then if the paper is an **anchor:**  
`combined = max(combined, 0.5)`.

**openFDA** rows that made the shortlist get a full 35/65 blend; those that did not only have `pre_score` (plus anchor rule if applicable).

## 8. Phase 3 — Final selection (`_combine_and_select`)

Papers are sorted by **`combined` descending**. Then UIDs are chosen in **three steps**, in order, until `top_n` slots are filled:

1. **Anchors** — every anchored UID is added first (in sorted order among anchors), without exceeding `top_n` in the loop logic (anchors are iterated in combined-score order).
2. **Source diversity** — for each **non-PubMed** source (e.g. **openFDA**), reserve **at least one** slot (`_SOURCE_MIN_SLOTS = 1`) for the **best combined-score** paper from that source not already selected. So if openFDA had any pool row, the **top openFDA row by combined score** is forced in before step 3 fills the rest (unless `top_n` is already full).
3. **Fill remaining slots** — highest `combined` among everyone not yet selected (PubMed and openFDA compete equally here).

Result is **deduped** and **truncated** to `top_n`.

**Interpretation for the UI:** Pool rows shown with strikethrough after triage are **not in** this final UID list. PubMed often dominates step 3 because combined scores are higher; step 2 is what **guarantees** at least one representative per external source when `top_n` allows it.

## 9. Special cases

| Situation | Behavior |
|-----------|----------|
| `len(pool) <= top_n` | **No triage competition** — every UID is returned in pool order (batch/stream). |
| Shortlist `<= top_n` | No LLM call; order is essentially shortlist iteration (stream) or all kept. |
| No target profile | **profile_signal** and **mesh_overlap** need profile; anchors may be empty; pre-score is mostly query vs title/abstract. |
| openFDA with no abstract | Pre-score leans on **title** + **profile_signal**; diversity + shortlist inclusion still help. |

## 10. Summary table: PubMed vs openFDA in triage

| Aspect | PubMed | openFDA (510(k)) |
|--------|--------|-------------------|
| **UID** | Usually PMID | K-number (`identifier`) |
| **Pre-score** | Often strong (abstract + MeSH) | Often weaker (missing abstract/MeSH) |
| **Anchor** | Yes, if title matches profile names | Same rule |
| **LLM shortlist** | Competes on pre-score | **Best per source** forced in + anchors |
| **LLM prompt** | `SOURCE=PubMed` | `SOURCE=openFDA`; rubric allows regulatory relevance |
| **Combined** | 35% pre + 65% LLM if scored | Same if in shortlist and parsed |
| **Final pick** | Competes in step 3 | **At least one** reserved in step 2 per non-PubMed source (if capacity) |

## References

- Implementation: `app/services/triage.py` — `prescore_paper`, `detect_anchors`, shortlist construction, `_build_scoring_prompt`, `_ScoredPaper.compute_combined`, `_combine_and_select`, `triage_papers`, `triage_papers_stream`
- Identity: `app/models/paper.py` — `Paper.uid`, `Paper.source`
