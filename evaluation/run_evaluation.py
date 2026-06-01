"""
Evaluation Runner — Task 7
==========================
Runs the full AI compiler pipeline on:
  - 10 real product prompts
  - 10 edge-case prompts

Tracks actual metrics:
  - success rate
  - retries per request
  - failure types
  - latency (overall + per stage)
  - execution score
  - clarification / assumption frequency
  - repair frequency

Usage:
  python evaluation/run_evaluation.py
  python evaluation/run_evaluation.py --live
  python evaluation/run_evaluation.py --stage1-only

Notes:
  - Default mode is dry-run summary.
  - --live runs the full pipeline if API keys are available.
  - Outputs JSON + CSV reports to evaluation/results/
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "evaluation" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_prompts() -> list[dict[str, Any]]:
    with open(ROOT / "evaluation" / "test_prompts.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    rows: list[dict[str, Any]] = []
    for category, prompts in data.items():
        for idx, item in enumerate(prompts, 1):
            row = dict(item)
            row["category"] = category
            row["case_id"] = f"{category}-{idx:02d}"
            rows.append(row)
    return rows


def dry_run_report() -> None:
    rows = _load_prompts()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[r["category"]].append(r)

    print("\n" + "=" * 72)
    print("AI COMPILER SYSTEM — EVALUATION FRAMEWORK")
    print("=" * 72)
    print(f"Dataset size: {len(rows)} prompts")
    print("Categories:   " + ", ".join(sorted(grouped.keys())))

    for category in sorted(grouped.keys()):
        prompts = grouped[category]
        print(f"\n[{category.upper()}] ({len(prompts)} prompts)")
        for item in prompts:
            prompt = item["prompt"].strip().replace("\n", " ")
            prompt = (prompt[:88] + "...") if len(prompt) > 88 else prompt
            print(f"  - {item['case_id']}: {prompt}")
            print(f"      expected: {item.get('expected_behavior', 'success')}")

    print("\nArtifacts generated in live mode:")
    print("  - evaluation/results/latest_report.json")
    print("  - evaluation/results/latest_report.csv")
    print("  - evaluation/results/latest_summary.md")
    print("=" * 72)


# ---------------------------------------------------------------------------
# Live evaluation
# ---------------------------------------------------------------------------

def _safe_len(x: Any) -> int:
    return len(x) if isinstance(x, (list, dict, tuple, set)) else 0


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _stage_call(fn, *args, **kwargs):
    started = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, _ms(started)


def _count_retries(stage_output: Any) -> int:
    if not isinstance(stage_output, dict):
        return 0
    for key in ("retry_count", "retries", "repair_attempts", "regen_count"):
        val = stage_output.get(key)
        if isinstance(val, int):
            return val
    return 0


def _extract_stage5_repair_count(stage5: dict) -> int:
    if not isinstance(stage5, dict):
        return 0
    for key in ("repair_count", "repairs_applied", "auto_repairs", "deterministic_repairs"):
        val = stage5.get(key)
        if isinstance(val, int):
            return val
    repairs = stage5.get("repairs") or stage5.get("applied_repairs") or []
    return len(repairs) if isinstance(repairs, list) else 0


def _failure_type(exc: Exception) -> str:
    name = type(exc).__name__
    msg = str(exc).lower()
    if "json" in msg:
        return "invalid_json"
    if "schema" in msg:
        return "schema_validation"
    if "auth" in msg:
        return "auth_error"
    if "timeout" in msg:
        return "timeout"
    if "key" in msg or "missing" in msg:
        return "missing_key"
    return name


def live_run(stage1_only: bool = False) -> None:
    sys.path.insert(0, str(ROOT))

    from pipeline.stage1_intent_extraction import extract_intent
    from pipeline.stage2_system_design import design_system
    from pipeline.stage3_schema_generation import generate_schemas
    from pipeline.stage4_refinement import refine_schemas
    from pipeline.stage5_validation_repair import validate_and_repair
    from pipeline.stage6_execution import check_execution_readiness

    rows = _load_prompts()
    all_results: list[dict[str, Any]] = []
    failure_counter: Counter[str] = Counter()
    category_counter: dict[str, Counter[str]] = defaultdict(Counter)
    overall_started = time.perf_counter()

    print(f"\nRunning evaluation on {len(rows)} prompts...\n")

    for item in rows:
        prompt = item["prompt"]
        category = item["category"]
        case_id = item["case_id"]

        stage_latencies: dict[str, float] = {}
        retries = 0
        repair_count = 0
        issues_count = 0
        assumptions_count = 0
        clarifications_count = 0
        execution_score = 0
        status = "success"
        failure_type = ""
        error_text = ""

        pipeline_state: dict[str, Any] = {}
        request_started = time.perf_counter()

        try:
            # Stage 1
            s1, t1 = _stage_call(extract_intent, prompt)
            stage_latencies["stage1_intent"] = t1
            retries += _count_retries(s1)
            clarifications_count += _safe_len(s1.get("clarifications_needed", []))
            assumptions_count += _safe_len(s1.get("assumptions", []))
            pipeline_state["intent"] = s1

            if not stage1_only:
                # Stage 2
                s2, t2 = _stage_call(design_system, s1)
                stage_latencies["stage2_design"] = t2
                retries += _count_retries(s2)
                pipeline_state["design"] = s2

                # Stage 3
                s3, t3 = _stage_call(generate_schemas, s2)
                stage_latencies["stage3_schema"] = t3
                retries += _count_retries(s3)
                pipeline_state["schemas"] = s3

                # Stage 4
                s4, t4 = _stage_call(refine_schemas, {"intent": s1, "design": s2, "schemas": s3})
                stage_latencies["stage4_refine"] = t4
                retries += _count_retries(s4)
                pipeline_state["schemas"] = s4.get("schemas", s4)

                # Stage 5
                s5, t5 = _stage_call(validate_and_repair, pipeline_state)
                stage_latencies["stage5_validate_repair"] = t5
                retries += _count_retries(s5)
                repair_count = _extract_stage5_repair_count(s5)
                issues_count += _safe_len(s5.get("issues", []))
                pipeline_state["schemas"] = s5.get("repaired_schemas") or s5.get("schemas") or pipeline_state.get("schemas")
                pipeline_state["stage5"] = s5

                # Stage 6
                s6, t6 = _stage_call(check_execution_readiness, pipeline_state)
                stage_latencies["stage6_execution"] = t6
                execution_score = int(s6.get("execution_score", 0) or 0)
                issues_count += _safe_len(s6.get("issues", []))
                assumptions_count += _safe_len(s6.get("assumptions", []))
                pipeline_state["stage6"] = s6

                if not s6.get("is_executable", False):
                    status = "partial"
                    failure_type = "not_executable"

        except Exception as exc:
            status = "failed"
            failure_type = _failure_type(exc)
            error_text = str(exc)[:300]
            failure_counter[failure_type] += 1
            category_counter[category][failure_type] += 1

        total_latency = _ms(request_started)
        result_row = {
            "case_id": case_id,
            "category": category,
            "status": status,
            "expected_behavior": item.get("expected_behavior", "success"),
            "prompt": prompt,
            "total_latency_ms": total_latency,
            "retries": retries,
            "repair_count": repair_count,
            "failure_type": failure_type,
            "error": error_text,
            "execution_score": execution_score,
            "clarifications": clarifications_count,
            "assumptions": assumptions_count,
            "issues": issues_count,
            **stage_latencies,
        }
        all_results.append(result_row)

        badge = "✓" if status == "success" else ("~" if status == "partial" else "✗")
        print(
            f"{badge} [{case_id}] {category:<10} "
            f"lat={total_latency:>8}ms  retries={retries:<2} repairs={repair_count:<2} "
            f"score={execution_score:<3} {failure_type or ''}"
        )

    total_runtime = _ms(overall_started)
    _write_reports(all_results, total_runtime, failure_counter, category_counter)


def _write_reports(
    rows: list[dict[str, Any]],
    total_runtime_ms: float,
    failure_counter: Counter[str],
    category_counter: dict[str, Counter[str]],
) -> None:
    total = len(rows)
    success_count = sum(1 for r in rows if r["status"] == "success")
    partial_count = sum(1 for r in rows if r["status"] == "partial")
    failed_count = sum(1 for r in rows if r["status"] == "failed")

    avg_latency = round(statistics.mean(r["total_latency_ms"] for r in rows), 2) if rows else 0
    p95_latency = round(_percentile([r["total_latency_ms"] for r in rows], 95), 2) if rows else 0
    avg_retries = round(statistics.mean(r["retries"] for r in rows), 2) if rows else 0
    avg_repairs = round(statistics.mean(r["repair_count"] for r in rows), 2) if rows else 0
    avg_execution_score = round(statistics.mean(r["execution_score"] for r in rows), 2) if rows else 0

    per_stage = _aggregate_stage_latencies(rows)

    summary = {
        "dataset_size": total,
        "success_count": success_count,
        "partial_count": partial_count,
        "failed_count": failed_count,
        "success_rate": round((success_count / total) * 100, 2) if total else 0,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "avg_retries_per_request": avg_retries,
        "avg_repairs_per_request": avg_repairs,
        "avg_execution_score": avg_execution_score,
        "failure_types": dict(failure_counter),
        "per_stage_avg_latency_ms": per_stage,
        "total_runtime_ms": total_runtime_ms,
        "category_breakdown": {
            cat: dict(counter) for cat, counter in category_counter.items()
        },
    }

    json_path = RESULTS_DIR / "latest_report.json"
    csv_path = RESULTS_DIR / "latest_report.csv"
    md_path = RESULTS_DIR / "latest_summary.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": rows}, f, indent=2)

    _write_csv(csv_path, rows)
    _write_markdown_summary(md_path, summary, rows)

    print("\n" + "=" * 72)
    print("EVALUATION RESULTS")
    print("=" * 72)
    print(f"Total prompts:            {summary['dataset_size']}")
    print(f"Success / Partial / Fail: {success_count} / {partial_count} / {failed_count}")
    print(f"Success rate:             {summary['success_rate']}%")
    print(f"Average latency:          {summary['avg_latency_ms']} ms")
    print(f"P95 latency:              {summary['p95_latency_ms']} ms")
    print(f"Avg retries/request:      {summary['avg_retries_per_request']}")
    print(f"Avg repairs/request:      {summary['avg_repairs_per_request']}")
    print(f"Avg execution score:      {summary['avg_execution_score']}")
    print(f"Failure types:            {dict(failure_counter)}")
    print("Per-stage average latency:")
    for stage, value in per_stage.items():
        print(f"  - {stage}: {value} ms")
    print("\nSaved:")
    print(f"  - {json_path}")
    print(f"  - {csv_path}")
    print(f"  - {md_path}")
    print("=" * 72)


def _aggregate_stage_latencies(rows: list[dict[str, Any]]) -> dict[str, float]:
    stage_keys = [
        "stage1_intent",
        "stage2_design",
        "stage3_schema",
        "stage4_refine",
        "stage5_validate_repair",
        "stage6_execution",
    ]
    out = {}
    for key in stage_keys:
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        out[key] = round(statistics.mean(vals), 2) if vals else 0.0
    return out


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown_summary(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    hardest = sorted(rows, key=lambda r: (r["status"] != "failed", r["total_latency_ms"]), reverse=True)[:5]
    easiest = sorted(rows, key=lambda r: (r["status"] == "success", -r["total_latency_ms"], r["execution_score"]), reverse=True)[:5]

    lines = [
        "# Evaluation Summary",
        "",
        "## Metrics",
        "",
        f"- Dataset size: {summary['dataset_size']}",
        f"- Success count: {summary['success_count']}",
        f"- Partial count: {summary['partial_count']}",
        f"- Failed count: {summary['failed_count']}",
        f"- Success rate: {summary['success_rate']}%",
        f"- Avg latency: {summary['avg_latency_ms']} ms",
        f"- P95 latency: {summary['p95_latency_ms']} ms",
        f"- Avg retries/request: {summary['avg_retries_per_request']}",
        f"- Avg repairs/request: {summary['avg_repairs_per_request']}",
        f"- Avg execution score: {summary['avg_execution_score']}",
        "",
        "## Failure Types",
        "",
    ]
    if summary["failure_types"]:
        for k, v in summary["failure_types"].items():
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- None")

    lines += ["", "## Slowest / Hardest Cases", ""]
    for r in hardest:
        lines.append(f"- {r['case_id']} ({r['category']}): {r['status']}, {r['total_latency_ms']} ms, failure={r['failure_type'] or 'none'}")

    lines += ["", "## Strongest Cases", ""]
    for r in easiest:
        lines.append(f"- {r['case_id']} ({r['category']}): {r['status']}, score={r['execution_score']}, latency={r['total_latency_ms']} ms")

    lines += ["", "## Per-Stage Average Latency", ""]
    for stage, value in summary["per_stage_avg_latency_ms"].items():
        lines.append(f"- {stage}: {value} ms")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if "--live" in sys.argv:
        live_run(stage1_only="--stage1-only" in sys.argv)
    else:
        dry_run_report()
