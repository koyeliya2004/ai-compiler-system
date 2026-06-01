"""
evaluation/metrics.py
=====================
Utility helpers for evaluation metrics and summaries.
Kept separate so it can be imported by notebooks, scripts, or dashboards.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
import statistics


def success_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    success = sum(1 for r in rows if r.get("status") == "success")
    return round(success / len(rows) * 100, 2)


def partial_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    partial = sum(1 for r in rows if r.get("status") == "partial")
    return round(partial / len(rows) * 100, 2)


def average_latency(rows: list[dict[str, Any]]) -> float:
    vals = [r.get("total_latency_ms", 0) for r in rows]
    return round(statistics.mean(vals), 2) if vals else 0.0


def p95_latency(rows: list[dict[str, Any]]) -> float:
    vals = sorted(r.get("total_latency_ms", 0) for r in rows)
    if not vals:
        return 0.0
    idx = max(0, int(round(0.95 * (len(vals) - 1))))
    return round(vals[idx], 2)


def average_retries(rows: list[dict[str, Any]]) -> float:
    vals = [r.get("retries", 0) for r in rows]
    return round(statistics.mean(vals), 2) if vals else 0.0


def average_repairs(rows: list[dict[str, Any]]) -> float:
    vals = [r.get("repair_count", 0) for r in rows]
    return round(statistics.mean(vals), 2) if vals else 0.0


def average_execution_score(rows: list[dict[str, Any]]) -> float:
    vals = [r.get("execution_score", 0) for r in rows]
    return round(statistics.mean(vals), 2) if vals else 0.0


def failure_types(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter(r.get("failure_type") for r in rows if r.get("failure_type"))
    return dict(counter)


def category_breakdown(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, Counter] = {}
    for row in rows:
        cat = row.get("category", "unknown")
        grouped.setdefault(cat, Counter())
        grouped[cat][row.get("status", "unknown")] += 1
    return {k: dict(v) for k, v in grouped.items()}
