"""Benchmark harness for evaluating the correlated-evidence retrieval pipeline.

Loads gold-list targets from ``targets.json``, runs the pipeline for each
seed, compares results against expected gold entries, computes 5 aggregate
metrics, and writes results to ``data/bench/benchmark_results.json`` and
``data/bench/benchmark_results.md``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel

from app.retrieval.models import BenchmarkTarget, RetrievalResponse
from app.retrieval.pipeline import retrieve_correlated_evidence

_DEFAULT_TARGETS = Path(__file__).parent / "targets.json"
_BENCH_DIR = Path(__file__).parent.parent.parent / "data" / "bench"


# ── Report models ────────────────────────────────────────────────────────

class GoldEntryResult(BaseModel):
    identifier: str
    tier: str
    relation_label: str
    expected_rank: int | None = None
    actual_rank: int | None = None
    expected_corr: float | None = None
    actual_corr: float | None = None
    expected_strength: float | None = None
    actual_strength: float | None = None
    expected_expl: float | None = None
    actual_expl: float | None = None
    found_in_results: bool = False


class TargetResult(BaseModel):
    target_id: str
    seed_identifier: str
    gold_entry_results: list[GoldEntryResult] = []
    self_match_at_rank1: bool = False
    tier1_in_top3_count: int = 0
    tier1_total: int = 0
    tier12_in_top10_count: int = 0
    tier12_total: int = 0
    tier5_avoided_count: int = 0
    tier5_total: int = 0
    top10_avg_expl: float = 0.0
    gold_tier12_avg_expl: float = 0.0
    pipeline_response: RetrievalResponse | None = None


class AggregateMetrics(BaseModel):
    top1_self_match_rate: float = 0.0
    top3_must_retrieve_recall: float = 0.0
    top10_correlated_coverage: float = 0.0
    hard_negative_avoidance_rate: float = 0.0
    explanation_usefulness_ratio: float = 0.0
    explanation_usefulness_top10_avg: float = 0.0
    explanation_usefulness_gold_avg: float = 0.0


class BenchmarkReport(BaseModel):
    target_results: list[TargetResult] = []
    aggregate_metrics: AggregateMetrics = AggregateMetrics()
    run_timestamp: str = ""
    metadata: dict[str, Any] = {}


# ── Harness ──────────────────────────────────────────────────────────────

class BenchmarkHarness:
    """Loads gold-list targets and evaluates retrieval pipeline performance."""

    def __init__(self, targets_path: str | None = None) -> None:
        path = Path(targets_path) if targets_path else _DEFAULT_TARGETS
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.targets: list[BenchmarkTarget] = [BenchmarkTarget(**t) for t in raw]

    async def run(
        self,
        target_ids: list[str] | None = None,
        write_output: bool = True,
    ) -> BenchmarkReport:
        """Run the benchmark and return a :class:`BenchmarkReport`."""
        selected = self.targets
        if target_ids:
            selected = [t for t in self.targets if t.target_id in target_ids]

        target_results: list[TargetResult] = []
        for target in selected:
            logger.info("Benchmark: running target {}", target.target_id)
            response = await retrieve_correlated_evidence(
                target.seed.identifier,
                profile_override=target.extracted_target_profile,
            )
            tr = self._evaluate_target(target, response)
            target_results.append(tr)

        agg = self._aggregate(target_results)
        report = BenchmarkReport(
            target_results=target_results,
            aggregate_metrics=agg,
            run_timestamp=datetime.now(tz=timezone.utc).isoformat(),
            metadata={"num_targets": len(selected)},
        )

        if write_output:
            self._write_output(report)

        return report

    def _evaluate_target(
        self, target: BenchmarkTarget, response: RetrievalResponse
    ) -> TargetResult:
        result_ids = [r.candidate.identifier for r in response.results]
        top3_ids = set(result_ids[:3])
        top10_ids = set(result_ids[:10])

        gold_entries: list[GoldEntryResult] = []
        tier1_found = 0
        tier1_total = 0
        tier12_found = 0
        tier12_total = 0
        tier5_avoided = 0
        tier5_total = 0
        gold_tier12_expl_scores: list[float] = []

        for gold in target.gold_list:
            actual_rank: int | None = None
            actual_corr: float | None = None
            actual_str: float | None = None
            actual_expl: float | None = None
            found = False

            for idx, r in enumerate(response.results):
                if r.candidate.identifier == gold.identifier:
                    actual_rank = idx + 1
                    actual_corr = r.correlation_score
                    actual_str = r.evidence_strength_score
                    actual_expl = r.explanation_value_score
                    found = True
                    break

            ge = GoldEntryResult(
                identifier=gold.identifier,
                tier=gold.tier,
                relation_label=gold.relation_label,
                expected_rank=gold.rank_expectation,
                actual_rank=actual_rank,
                expected_corr=gold.correlation_score,
                actual_corr=actual_corr,
                expected_strength=gold.evidence_strength_score,
                actual_strength=actual_str,
                expected_expl=gold.explanation_value_score,
                actual_expl=actual_expl,
                found_in_results=found,
            )
            gold_entries.append(ge)

            if gold.tier in ("Tier1",):
                tier1_total += 1
                if gold.identifier in top3_ids:
                    tier1_found += 1
            if gold.tier in ("Tier1", "Tier2"):
                tier12_total += 1
                if gold.identifier in top10_ids:
                    tier12_found += 1
                if gold.explanation_value_score is not None:
                    gold_tier12_expl_scores.append(gold.explanation_value_score)
            if gold.tier == "Tier5":
                tier5_total += 1
                if gold.identifier not in top10_ids:
                    tier5_avoided += 1

        self_at_1 = (
            len(response.results) > 0
            and response.results[0].candidate.identifier == target.seed.identifier
        )

        top10_expl = [
            r.explanation_value_score for r in response.results[:10]
        ]
        top10_avg = sum(top10_expl) / len(top10_expl) if top10_expl else 0.0
        gold_avg = (
            sum(gold_tier12_expl_scores) / len(gold_tier12_expl_scores)
            if gold_tier12_expl_scores
            else 0.0
        )

        return TargetResult(
            target_id=target.target_id,
            seed_identifier=target.seed.identifier,
            gold_entry_results=gold_entries,
            self_match_at_rank1=self_at_1,
            tier1_in_top3_count=tier1_found,
            tier1_total=tier1_total,
            tier12_in_top10_count=tier12_found,
            tier12_total=tier12_total,
            tier5_avoided_count=tier5_avoided,
            tier5_total=tier5_total,
            top10_avg_expl=round(top10_avg, 4),
            gold_tier12_avg_expl=round(gold_avg, 4),
            pipeline_response=response,
        )

    def _aggregate(self, results: list[TargetResult]) -> AggregateMetrics:
        n = len(results) or 1
        self_rate = sum(1 for r in results if r.self_match_at_rank1) / n
        recall_vals = [
            r.tier1_in_top3_count / r.tier1_total
            if r.tier1_total > 0
            else 1.0
            for r in results
        ]
        coverage_vals = [
            r.tier12_in_top10_count / r.tier12_total
            if r.tier12_total > 0
            else 1.0
            for r in results
        ]
        avoid_vals = [
            r.tier5_avoided_count / r.tier5_total
            if r.tier5_total > 0
            else 1.0
            for r in results
        ]
        top10_avg = sum(r.top10_avg_expl for r in results) / n
        gold_avg = sum(r.gold_tier12_avg_expl for r in results) / n
        ratio = top10_avg / gold_avg if gold_avg > 0 else 0.0

        return AggregateMetrics(
            top1_self_match_rate=round(self_rate, 4),
            top3_must_retrieve_recall=round(sum(recall_vals) / n, 4),
            top10_correlated_coverage=round(sum(coverage_vals) / n, 4),
            hard_negative_avoidance_rate=round(sum(avoid_vals) / n, 4),
            explanation_usefulness_ratio=round(ratio, 4),
            explanation_usefulness_top10_avg=round(top10_avg, 4),
            explanation_usefulness_gold_avg=round(gold_avg, 4),
        )

    def _write_output(self, report: BenchmarkReport) -> None:
        _BENCH_DIR.mkdir(parents=True, exist_ok=True)

        # --- JSON ---
        json_path = _BENCH_DIR / "benchmark_results.json"
        # Exclude full pipeline_response from JSON to keep it manageable
        json_data = report.model_dump(mode="json")
        for tr in json_data.get("target_results", []):
            tr.pop("pipeline_response", None)
        json_path.write_text(json.dumps(json_data, indent=2), encoding="utf-8")
        logger.info("Benchmark results written to {}", json_path)

        # --- Markdown ---
        md_path = _BENCH_DIR / "benchmark_results.md"
        md_path.write_text(self._render_markdown(report), encoding="utf-8")
        logger.info("Benchmark summary written to {}", md_path)

    def _render_markdown(self, report: BenchmarkReport) -> str:
        lines: list[str] = []
        agg = report.aggregate_metrics

        lines.append("# Benchmark Results\n")
        lines.append(f"**Timestamp:** {report.run_timestamp}\n")
        lines.append(f"**Targets evaluated:** {report.metadata.get('num_targets', 0)}\n")

        lines.append("\n## Aggregate Metrics\n")
        lines.append("| Metric | Value | Target | Pass |")
        lines.append("|--------|-------|--------|------|")
        lines.append(f"| Top-1 self-match rate | {agg.top1_self_match_rate:.2%} | 100% | {'PASS' if agg.top1_self_match_rate >= 1.0 else 'FAIL'} |")
        lines.append(f"| Top-3 must-retrieve recall | {agg.top3_must_retrieve_recall:.2%} | >= 70% | {'PASS' if agg.top3_must_retrieve_recall >= 0.7 else 'FAIL'} |")
        lines.append(f"| Top-10 correlated coverage | {agg.top10_correlated_coverage:.2%} | >= 60% | {'PASS' if agg.top10_correlated_coverage >= 0.6 else 'FAIL'} |")
        lines.append(f"| Hard-negative avoidance | {agg.hard_negative_avoidance_rate:.2%} | >= 90% | {'PASS' if agg.hard_negative_avoidance_rate >= 0.9 else 'FAIL'} |")
        lines.append(f"| Explanation usefulness ratio | {agg.explanation_usefulness_ratio:.4f} | > 0 | {'PASS' if agg.explanation_usefulness_ratio > 0 else 'FAIL'} |")

        for tr in report.target_results:
            lines.append(f"\n## Target: `{tr.target_id}`\n")
            lines.append(f"**Seed:** `{tr.seed_identifier}`")
            lines.append(f"**Self at rank 1:** {'Yes' if tr.self_match_at_rank1 else 'No'}")
            lines.append(f"**Tier1 in top-3:** {tr.tier1_in_top3_count}/{tr.tier1_total}")
            lines.append(f"**Tier1+2 in top-10:** {tr.tier12_in_top10_count}/{tr.tier12_total}")
            lines.append(f"**Tier5 avoided:** {tr.tier5_avoided_count}/{tr.tier5_total}\n")

            lines.append("| ID | Tier | Label | Exp Rank | Act Rank | Exp Corr | Act Corr | Exp Str | Act Str | Exp Expl | Act Expl | Found |")
            lines.append("|-----|------|-------|----------|----------|----------|----------|---------|---------|----------|----------|-------|")
            for ge in tr.gold_entry_results:
                er = ge.expected_rank or "-"
                ar = ge.actual_rank or "-"
                ec = f"{ge.expected_corr:.2f}" if ge.expected_corr is not None else "-"
                ac = f"{ge.actual_corr:.2f}" if ge.actual_corr is not None else "-"
                es = f"{ge.expected_strength:.2f}" if ge.expected_strength is not None else "-"
                a_s = f"{ge.actual_strength:.2f}" if ge.actual_strength is not None else "-"
                ee = f"{ge.expected_expl:.2f}" if ge.expected_expl is not None else "-"
                ae = f"{ge.actual_expl:.2f}" if ge.actual_expl is not None else "-"
                found = "Yes" if ge.found_in_results else "No"
                ident = ge.identifier[:30]
                lines.append(f"| {ident} | {ge.tier} | {ge.relation_label} | {er} | {ar} | {ec} | {ac} | {es} | {a_s} | {ee} | {ae} | {found} |")

        lines.append("")
        return "\n".join(lines)

    def compute_metrics(self, results: dict[str, Any]) -> dict[str, Any]:
        """Compatibility method: compute metrics from raw results dict."""
        return results
