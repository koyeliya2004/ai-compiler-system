"""
runtime/executor.py
====================
Saves Stage 6 artifacts to disk so they can be used directly.
Called after the pipeline completes successfully.

Usage:
    from runtime.executor import save_artifacts
    save_artifacts(stage6_output, output_dir="./runtime/output")
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def save_artifacts(stage6_output: dict, output_dir: str = "./runtime/output") -> dict[str, str]:
    """
    Writes all generated artifacts to disk.
    Returns a dict of { artifact_name: file_path }.
    """
    artifacts = stage6_output.get("artifacts", {})
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}

    # SQL DDL
    if sql := artifacts.get("sql_ddl"):
        path = base / "schema.sql"
        path.write_text(sql, encoding="utf-8")
        saved["sql_ddl"] = str(path)

    # FastAPI router
    if router := artifacts.get("fastapi_routes"):
        path = base / "router.py"
        path.write_text(router, encoding="utf-8")
        saved["fastapi_routes"] = str(path)

    # React pages
    if pages := artifacts.get("react_pages"):
        pages_dir = base / "pages"
        pages_dir.mkdir(exist_ok=True)
        for filename, content in pages.items():
            page_path = pages_dir / filename
            page_path.write_text(content, encoding="utf-8")
        saved["react_pages"] = str(pages_dir)

    # Docker Compose
    if compose := artifacts.get("docker_compose"):
        path = base / "docker-compose.yml"
        path.write_text(compose, encoding="utf-8")
        saved["docker_compose"] = str(path)

    # Write full Stage 6 output as JSON for debugging
    meta_path = base / "stage6_output.json"
    meta_path.write_text(json.dumps(stage6_output, indent=2), encoding="utf-8")
    saved["metadata"] = str(meta_path)

    return saved


def execution_report(stage6_output: dict) -> str:
    """
    Returns a human-readable execution report string.
    """
    score      = stage6_output.get("execution_score", 0)
    executable = stage6_output.get("is_executable", False)
    issues     = stage6_output.get("issues", [])
    assumptions = stage6_output.get("assumptions", [])
    sim        = stage6_output.get("simulation", {})
    boot_log   = sim.get("boot_log", [])
    route_table = sim.get("route_table", [])
    db_plan    = sim.get("db_plan", [])
    auth_matrix = sim.get("auth_matrix", [])

    status_emoji = "✅" if executable else ("⚠️" if score >= 60 else "❌")

    lines = [
        "=" * 60,
        f"STAGE 6 — EXECUTION REPORT  {status_emoji}",
        "=" * 60,
        f"Execution Score : {score}/100",
        f"Is Executable   : {executable}",
        "",
        "── Boot Log ──────────────────────────────────────────────",
    ]
    for entry in boot_log:
        lines.append(f"  ▸ {entry}")

    lines += [
        "",
        "── Database Plan ─────────────────────────────────────────",
        f"  {'Table':<30} {'Cols':>4}  {'DDL Ready':>9}",
        f"  {'-'*30} {'----':>4}  {'---------':>9}",
    ]
    for tbl in db_plan:
        ready = "✓" if tbl.get("ddl_ready") else "✗"
        lines.append(f"  {tbl['table']:<30} {tbl['columns']:>4}  {ready:>9}")

    lines += [
        "",
        "── API Route Table ───────────────────────────────────────",
        f"  {'Method':<8} {'Path':<40} {'Auth':>5}",
        f"  {'------':<8} {'----':<40} {'----':>5}",
    ]
    for rt in route_table:
        auth_str = "🔒" if rt.get("auth") else "  "
        lines.append(f"  {rt['method']:<8} {rt['path']:<40} {auth_str:>5}")

    lines += [
        "",
        "── Auth Matrix ───────────────────────────────────────────",
    ]
    for am in auth_matrix:
        perm_str = ", ".join(am.get("permissions", [])) or "(none defined)"
        lines.append(f"  {am['role']}: {perm_str}")

    if assumptions:
        lines += ["", "── Assumptions ───────────────────────────────────────────"]
        for a in assumptions:
            lines.append(f"  ⚑ {a}")

    if issues:
        lines += ["", "── Issues (Blocking) ─────────────────────────────────────"]
        for i in issues:
            lines.append(f"  ✗ {i}")

    lines += ["", "=" * 60]
    return "\n".join(lines)
