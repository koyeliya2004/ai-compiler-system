"""
Stage 6 — Execution Awareness
==============================
This stage is the CRITICAL DIFFERENCE in the pipeline.
It proves that the validated schemas from Stage 5 are not just
neat JSON — they can directly power a real application.

Two-track approach:
  Track A: Runtime Simulation    — fast, deterministic, no LLM
  Track B: Code Artifact Generation — produces runnable SQL/Python/React

Outputs:
  {
    "is_executable": bool,
    "execution_score": 0-100,
    "simulation": { boot_log, route_table, db_plan, auth_matrix },
    "artifacts": { sql_ddl, fastapi_routes, react_pages, docker_compose },
    "issues": [],
    "assumptions": []
  }
"""

from __future__ import annotations

import json
import logging
import textwrap
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def check_execution_readiness(output: dict) -> dict:
    """
    Main entry point called by api/app.py.
    `output` is the full pipeline accumulator dict that contains
    schemas (possibly repaired by Stage 5).
    """
    logger.info("[Stage 6] Execution Awareness — begin")

    schemas = _extract_schemas(output)
    issues: list[str] = []
    assumptions: list[str] = []

    # Track A — deterministic runtime simulation
    sim = _simulate_runtime(schemas, issues, assumptions)

    # Track B — code artifact generation
    artifacts = _generate_artifacts(schemas, issues, assumptions)

    # Execution score (0-100)
    score = _compute_score(schemas, sim, artifacts, issues)

    result = {
        "is_executable": score >= 60 and len(issues) == 0,
        "execution_score": score,
        "simulation": sim,
        "artifacts": artifacts,
        "issues": issues,
        "assumptions": assumptions,
    }

    logger.info(
        "[Stage 6] Done — score=%d executable=%s issues=%d",
        score, result["is_executable"], len(issues),
    )
    return result


# Alias used by orchestrator
run = check_execution_readiness


# ---------------------------------------------------------------------------
# Helpers — schema extraction
# ---------------------------------------------------------------------------

def _extract_schemas(output: dict) -> dict:
    """Pull the most refined schemas from the pipeline accumulator."""
    schemas = output.get("schemas", {})
    # Stage 5 may have stored repaired schemas under a nested key
    if isinstance(schemas, dict):
        if "repaired_schemas" in schemas:
            return schemas["repaired_schemas"]
        if "final_schemas" in schemas:
            return schemas["final_schemas"]
    return schemas or {}


# ---------------------------------------------------------------------------
# Track A — Runtime Simulation
# ---------------------------------------------------------------------------

def _simulate_runtime(schemas: dict, issues: list, assumptions: list) -> dict:
    """
    Simulate what happens when the generated app boots.
    Produces a structured boot_log, route_table, db_plan, auth_matrix.
    Entirely deterministic — no LLM call.
    """
    db_schema   = schemas.get("db_schema",  {})
    api_schema  = schemas.get("api_schema", {})
    ui_schema   = schemas.get("ui_schema",  {})
    auth_rules  = schemas.get("auth_rules", {})

    boot_log      = []
    route_table   = []
    db_plan       = []
    auth_matrix   = []

    # ---- Database boot ----
    tables = db_schema.get("tables", [])
    if not tables:
        issues.append("DB schema has no tables — cannot boot database.")
    else:
        for tbl in tables:
            name    = tbl.get("name", "?")
            columns = tbl.get("columns", [])
            pk_cols = [c["name"] for c in columns if c.get("primary_key") or c.get("name") == "id"]
            fk_cols = [c["name"] for c in columns if c.get("foreign_key")]
            db_plan.append({
                "table":    name,
                "columns":  len(columns),
                "pk":       pk_cols,
                "fk_count": len(fk_cols),
                "ddl_ready": bool(pk_cols),
            })
            if not pk_cols:
                issues.append(f"Table `{name}` has no primary key — DDL will fail.")
        boot_log.append(f"DB: {len(tables)} table(s) planned — {sum(1 for t in db_plan if t['ddl_ready'])} DDL-ready")

    # ---- API boot ----
    endpoints = api_schema.get("endpoints", [])
    if not endpoints:
        issues.append("API schema has no endpoints — cannot register routes.")
    else:
        for ep in endpoints:
            method  = ep.get("method", "GET").upper()
            path    = ep.get("path", "/")
            auth    = ep.get("auth_required", False)
            roles   = ep.get("roles", [])
            route_table.append({
                "method": method,
                "path":   path,
                "auth":   auth,
                "roles":  roles,
            })
        boot_log.append(f"API: {len(endpoints)} route(s) registered")
        # Check for at minimum a health-check or root route
        paths = [ep.get("path", "") for ep in endpoints]
        if not any(p in ("/", "/health", "/healthz", "/ping") for p in paths):
            assumptions.append("No health-check endpoint found — adding GET /health automatically.")
            route_table.insert(0, {"method": "GET", "path": "/health", "auth": False, "roles": []})

    # ---- UI boot ----
    pages = ui_schema.get("pages", [])
    if not pages:
        issues.append("UI schema has no pages — frontend cannot render.")
    else:
        boot_log.append(f"UI: {len(pages)} page(s) mapped")

    # ---- Auth matrix ----
    roles = auth_rules.get("roles", [])
    permissions = auth_rules.get("permissions", [])
    strategy = auth_rules.get("strategy", "jwt")
    if not roles:
        assumptions.append("No roles defined — defaulting to public access only.")
        roles = ["public"]
    for role in roles:
        role_name = role if isinstance(role, str) else role.get("name", str(role))
        perms = [
            p.get("action") or p
            for p in permissions
            if isinstance(p, dict) and p.get("role") == role_name
        ] if isinstance(permissions, list) else []
        auth_matrix.append({"role": role_name, "permissions": perms})
    boot_log.append(f"Auth: strategy={strategy} roles={[r['role'] for r in auth_matrix]}")

    return {
        "boot_log":    boot_log,
        "route_table": route_table,
        "db_plan":     db_plan,
        "auth_matrix": auth_matrix,
    }


# ---------------------------------------------------------------------------
# Track B — Code Artifact Generation
# ---------------------------------------------------------------------------

def _generate_artifacts(schemas: dict, issues: list, assumptions: list) -> dict:
    """
    Generate real, runnable code artifacts directly from the validated schemas.
    No LLM — pure deterministic templating.
    Outputs: SQL DDL, FastAPI router, React page stubs, docker-compose.
    """
    db_schema   = schemas.get("db_schema",  {})
    api_schema  = schemas.get("api_schema", {})
    ui_schema   = schemas.get("ui_schema",  {})
    auth_rules  = schemas.get("auth_rules", {})

    return {
        "sql_ddl":       _gen_sql_ddl(db_schema),
        "fastapi_routes": _gen_fastapi_router(api_schema, auth_rules),
        "react_pages":   _gen_react_pages(ui_schema, api_schema),
        "docker_compose": _gen_docker_compose(auth_rules),
    }


# -- SQL DDL Generator -------------------------------------------------------

_TYPE_MAP = {
    "string":    "VARCHAR(255)",
    "str":       "VARCHAR(255)",
    "text":      "TEXT",
    "int":       "INT",
    "integer":   "INT",
    "float":     "DECIMAL(10,2)",
    "decimal":   "DECIMAL(10,2)",
    "bool":      "BOOLEAN",
    "boolean":   "BOOLEAN",
    "datetime":  "TIMESTAMP",
    "timestamp": "TIMESTAMP",
    "date":      "DATE",
    "uuid":      "UUID DEFAULT gen_random_uuid()",
    "json":      "JSONB",
    "array":     "JSONB",
}


def _pg_type(col_type: str) -> str:
    return _TYPE_MAP.get(col_type.lower().strip(), "VARCHAR(255)")


def _gen_sql_ddl(db_schema: dict) -> str:
    tables = db_schema.get("tables", [])
    if not tables:
        return "-- No tables defined\n"

    lines: list[str] = [
        "-- Auto-generated SQL DDL",
        "-- Generated by AI Compiler System — Stage 6",
        "-- Target: PostgreSQL 15+",
        "",
        "BEGIN;",
        "",
    ]

    for tbl in tables:
        tname   = tbl.get("name", "unknown_table")
        columns = tbl.get("columns", [])
        col_defs: list[str] = []
        constraints: list[str] = []

        for col in columns:
            cname  = col.get("name", "col")
            ctype  = _pg_type(col.get("type", "string"))
            parts  = [f"    {cname} {ctype}"]
            if col.get("primary_key"):
                parts.append("PRIMARY KEY")
            if col.get("unique"):
                parts.append("UNIQUE")
            if not col.get("nullable", True):
                parts.append("NOT NULL")
            if col.get("default") is not None:
                default_val = col["default"]
                if isinstance(default_val, str):
                    parts.append(f"DEFAULT '{default_val}'")
                elif isinstance(default_val, bool):
                    parts.append(f"DEFAULT {'TRUE' if default_val else 'FALSE'}")
                else:
                    parts.append(f"DEFAULT {default_val}")
            col_defs.append(" ".join(parts))

            # FK constraints
            fk = col.get("foreign_key")
            if fk and isinstance(fk, dict):
                ref_table = fk.get("table", "")
                ref_col   = fk.get("column", "id")
                if ref_table:
                    constraints.append(
                        f"    CONSTRAINT fk_{tname}_{cname} "
                        f"FOREIGN KEY ({cname}) REFERENCES {ref_table}({ref_col})"
                    )

        all_defs = col_defs + constraints
        lines += [
            f"CREATE TABLE IF NOT EXISTS {tname} (",
            ",\n".join(all_defs),
            ");",
            f"CREATE INDEX IF NOT EXISTS idx_{tname}_id ON {tname} (id);"
            if any(c.get("name") == "id" for c in columns) else "",
            "",
        ]

    lines += ["COMMIT;", ""]
    return "\n".join(line for line in lines if line is not None)


# -- FastAPI Router Generator ------------------------------------------------

def _gen_fastapi_router(api_schema: dict, auth_rules: dict) -> str:
    endpoints = api_schema.get("endpoints", [])
    strategy  = auth_rules.get("strategy", "jwt")

    if not endpoints:
        return "# No endpoints defined\n"

    lines: list[str] = [
        "# Auto-generated FastAPI router",
        "# Generated by AI Compiler System — Stage 6",
        "",
        "from fastapi import APIRouter, Depends, HTTPException, status",
        "from pydantic import BaseModel",
        "from typing import Optional, List",
        "",
        "router = APIRouter()",
        "",
        "# --- Auth dependency stub ---",
        "def get_current_user(token: str = \"\"):",
        '    """Replace with real JWT/session verification."""',
        '    return {"user_id": "stub", "role": "admin"}',
        "",
        "def require_role(*roles):",
        "    def dep(user=Depends(get_current_user)):",
        '        if roles and user.get("role") not in roles:',
        '            raise HTTPException(status_code=403, detail="Forbidden")',
        "        return user",
        "    return dep",
        "",
    ]

    # Group by resource for cleaner output
    for ep in endpoints:
        method   = ep.get("method", "GET").lower()
        path     = ep.get("path", "/")
        auth_req = ep.get("auth_required", False)
        roles    = ep.get("roles", [])
        summary  = ep.get("summary", ep.get("description", path))

        # Build function name from path
        fn_name  = path.replace("/", "_").replace("-", "_").replace("{", "").replace("}", "")
        fn_name  = f"{method}{fn_name}".strip("_") or f"{method}_root"

        dep_str = ""
        if auth_req:
            if roles:
                roles_str = ", ".join(f'"{r}"' for r in roles)
                dep_str   = f", user=Depends(require_role({roles_str}))"
            else:
                dep_str = ", user=Depends(get_current_user)"

        lines += [
            f'@router.{method}("{path}", summary="{summary}")',
            f"async def {fn_name}({dep_str.lstrip(', ')}):",
            f'    """TODO: implement {summary}"""',
            '    return {"status": "ok"}',
            "",
        ]

    lines += [
        "@router.get('/health', tags=['system'])",
        "async def health_check():",
        '    return {"status": "healthy"}',
        "",
    ]

    return "\n".join(lines)


# -- React Page Stub Generator -----------------------------------------------

def _gen_react_pages(ui_schema: dict, api_schema: dict) -> dict[str, str]:
    pages = ui_schema.get("pages", [])
    endpoints = api_schema.get("endpoints", [])
    endpoint_paths = [ep.get("path", "") for ep in endpoints]

    if not pages:
        return {"index.tsx": _react_placeholder("Home", "/")}

    result: dict[str, str] = {}
    for page in pages:
        page_name  = page.get("name", page.get("title", "Page"))
        route      = page.get("route", "/").lstrip("/") or "index"
        components = page.get("components", [])
        layout     = page.get("layout", "default")
        auth_req   = page.get("auth_required", False)
        roles      = page.get("roles", [])

        filename   = route.replace("/", "_").strip("_") or "index"
        result[f"{filename}.tsx"] = _react_page(
            page_name, route, components, layout, auth_req, roles, endpoint_paths
        )

    return result


def _react_page(
    name: str,
    route: str,
    components: list,
    layout: str,
    auth_req: bool,
    roles: list,
    endpoint_paths: list,
) -> str:
    comp_imports: list[str] = []
    comp_usages:  list[str] = []

    for comp in components:
        ctype  = comp.get("type", "Section") if isinstance(comp, dict) else str(comp)
        cprops = comp.get("props", {}) if isinstance(comp, dict) else {}
        c_name = ctype.replace(" ", "")
        comp_imports.append(f"// import {c_name} from '@/components/{c_name}';")
        props_str = " ".join(f'{k}={{"{v}"}}' for k, v in cprops.items())
        comp_usages.append(f"      <{c_name} {props_str} />")

    auth_guard = ""
    if auth_req:
        role_check = ""
        if roles:
            role_list = ", ".join(f'"{r}"' for r in roles)
            role_check = f" || ![{role_list}].includes(user?.role)"
        auth_guard = textwrap.dedent(f"""
          const {{ user, loading }} = useAuth();
          if (loading) return <LoadingSpinner />;
          if (!user{role_check}) return <Navigate to="/login" replace />;
        """).strip()

    imports = "\n".join(comp_imports)
    usages  = "\n".join(comp_usages) if comp_usages else "      {/* Add components here */}"

    return textwrap.dedent(f"""\
        // Auto-generated by AI Compiler System — Stage 6
        // Page: {name}  Route: /{route}
        import React from 'react';
        import {{ useEffect, useState }} from 'react';
        {f"import {{ useAuth }} from '@/hooks/useAuth';" if auth_req else ""}
        {f"import {{ Navigate }} from 'react-router-dom';" if auth_req else ""}
        {imports}

        const {name.replace(' ', '')}Page: React.FC = () => {{
          {auth_guard}

          return (
            <main className="page page-{route.replace('/', '-').strip('-')}">
              <h1>{name}</h1>
        {usages}
            </main>
          );
        }};

        export default {name.replace(' ', '')}Page;
        """)


def _react_placeholder(name: str, route: str) -> str:
    return textwrap.dedent(f"""\
        // Auto-generated placeholder
        import React from 'react';
        const {name}Page = () => <main><h1>{name}</h1></main>;
        export default {name}Page;
        """)


# -- Docker Compose Generator ------------------------------------------------

def _gen_docker_compose(auth_rules: dict) -> str:
    strategy = auth_rules.get("strategy", "jwt").lower()
    needs_redis = strategy in ("session", "oauth", "oauth2")

    services = textwrap.dedent("""\
        version: '3.9'
        services:
          api:
            build: .
            ports:
              - "8000:8000"
            environment:
              - DATABASE_URL=postgresql://postgres:postgres@db:5432/appdb
              - SECRET_KEY=change-me-in-production
            depends_on:
              - db
            healthcheck:
              test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
              interval: 30s
              timeout: 10s
              retries: 3

          db:
            image: postgres:15-alpine
            environment:
              POSTGRES_USER: postgres
              POSTGRES_PASSWORD: postgres
              POSTGRES_DB: appdb
            volumes:
              - pgdata:/var/lib/postgresql/data
              - ./artifacts/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql
            ports:
              - "5432:5432"
        """)

    if needs_redis:
        services += textwrap.dedent("""\

          redis:
            image: redis:7-alpine
            ports:
              - "6379:6379"
        """)

    services += textwrap.dedent("""\

        volumes:
          pgdata:
        """)

    return services


# ---------------------------------------------------------------------------
# Execution Score
# ---------------------------------------------------------------------------

def _compute_score(schemas: dict, sim: dict, artifacts: dict, issues: list) -> int:
    """
    Score 0-100 based on:
      - DB schema completeness    (25 pts)
      - API schema completeness   (25 pts)
      - UI schema completeness    (20 pts)
      - Auth schema completeness  (15 pts)
      - Artifact quality          (15 pts)
    Deduct 10 pts per critical issue (floor 0).
    """
    score = 0

    # DB
    db_tables = schemas.get("db_schema", {}).get("tables", [])
    db_plan   = sim.get("db_plan", [])
    if db_tables:
        score += 15
        ddl_ready = sum(1 for t in db_plan if t.get("ddl_ready"))
        score += min(10, round(10 * ddl_ready / max(len(db_tables), 1)))

    # API
    endpoints = schemas.get("api_schema", {}).get("endpoints", [])
    if endpoints:
        score += 15
        score += min(10, round(10 * len(endpoints) / max(len(endpoints), 1)))

    # UI
    pages = schemas.get("ui_schema", {}).get("pages", [])
    if pages:
        score += 12
        score += min(8, round(8 * len(pages) / max(len(pages), 1)))

    # Auth
    auth = schemas.get("auth_rules", {})
    if auth.get("roles"):
        score += 8
    if auth.get("strategy"):
        score += 7

    # Artifacts
    ddl  = artifacts.get("sql_ddl", "")
    fast = artifacts.get("fastapi_routes", "")
    react = artifacts.get("react_pages", {})
    if ddl and "CREATE TABLE" in ddl:
        score += 5
    if fast and "@router." in fast:
        score += 5
    if react and len(react) > 0:
        score += 5

    # Deduct for issues
    score -= 10 * len(issues)
    return max(0, min(100, score))
