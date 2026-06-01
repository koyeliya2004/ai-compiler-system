"""
tests/test_stage6.py
======================
Unit tests for Stage 6 — Execution Awareness.
Fully deterministic — no LLM calls required.
"""

import json
import pytest
from pipeline.stage6_execution import check_execution_readiness, _simulate_runtime, _generate_artifacts, _compute_score


# ─── Fixtures ────────────────────────────────────────────────────────────────

CRM_SCHEMAS = {
    "db_schema": {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "type": "uuid", "primary_key": True, "nullable": False},
                    {"name": "email", "type": "string", "unique": True, "nullable": False},
                    {"name": "role", "type": "string", "nullable": False, "default": "user"},
                    {"name": "created_at", "type": "timestamp", "nullable": False},
                ]
            },
            {
                "name": "contacts",
                "columns": [
                    {"name": "id", "type": "uuid", "primary_key": True},
                    {"name": "user_id", "type": "uuid", "foreign_key": {"table": "users", "column": "id"}},
                    {"name": "name", "type": "string", "nullable": False},
                    {"name": "email", "type": "string"},
                    {"name": "phone", "type": "string"},
                ]
            },
            {
                "name": "deals",
                "columns": [
                    {"name": "id", "type": "uuid", "primary_key": True},
                    {"name": "contact_id", "type": "uuid", "foreign_key": {"table": "contacts", "column": "id"}},
                    {"name": "value", "type": "decimal"},
                    {"name": "status", "type": "string", "default": "open"},
                ]
            },
        ]
    },
    "api_schema": {
        "endpoints": [
            {"method": "POST", "path": "/auth/login",     "auth_required": False, "summary": "Login"},
            {"method": "POST", "path": "/auth/register",  "auth_required": False, "summary": "Register"},
            {"method": "GET",  "path": "/contacts",       "auth_required": True,  "roles": ["admin", "user"]},
            {"method": "POST", "path": "/contacts",       "auth_required": True,  "roles": ["admin", "user"]},
            {"method": "GET",  "path": "/contacts/{id}",  "auth_required": True,  "roles": ["admin", "user"]},
            {"method": "PUT",  "path": "/contacts/{id}",  "auth_required": True,  "roles": ["admin", "user"]},
            {"method": "DELETE","path": "/contacts/{id}", "auth_required": True,  "roles": ["admin"]},
            {"method": "GET",  "path": "/deals",          "auth_required": True,  "roles": ["admin", "user"]},
            {"method": "GET",  "path": "/analytics",      "auth_required": True,  "roles": ["admin"]},
        ]
    },
    "ui_schema": {
        "pages": [
            {"name": "Login",     "route": "/login",     "auth_required": False, "components": [{"type": "LoginForm"}]},
            {"name": "Dashboard", "route": "/dashboard", "auth_required": True,  "roles": ["admin", "user"], "components": [{"type": "StatsPanel"}, {"type": "RecentActivity"}]},
            {"name": "Contacts",  "route": "/contacts",  "auth_required": True,  "roles": ["admin", "user"], "components": [{"type": "Table", "props": {"resource": "contacts"}}]},
            {"name": "Analytics", "route": "/analytics", "auth_required": True,  "roles": ["admin"],         "components": [{"type": "Chart", "props": {"type": "bar"}}]},
        ]
    },
    "auth_rules": {
        "strategy": "jwt",
        "roles": ["admin", "user"],
        "permissions": [
            {"role": "admin", "action": "*"},
            {"role": "user",  "action": "read:contacts"},
            {"role": "user",  "action": "write:contacts"},
        ]
    }
}

EMPTY_SCHEMAS: dict = {}

NO_PK_SCHEMAS = {
    "db_schema": {
        "tables": [
            {"name": "items", "columns": [{"name": "name", "type": "string"}]}
        ]
    },
    "api_schema": {"endpoints": []},
    "ui_schema": {"pages": []},
    "auth_rules": {},
}


# ─── Stage 6 Integration Tests ────────────────────────────────────────────────

class TestCheckExecutionReadiness:
    def test_full_crm_is_executable(self):
        out = check_execution_readiness({"schemas": CRM_SCHEMAS})
        assert out["is_executable"] is True
        assert out["execution_score"] >= 60

    def test_empty_schemas_not_executable(self):
        out = check_execution_readiness({"schemas": EMPTY_SCHEMAS})
        assert out["is_executable"] is False
        assert out["execution_score"] < 60

    def test_output_keys_present(self):
        out = check_execution_readiness({"schemas": CRM_SCHEMAS})
        for key in ("is_executable", "execution_score", "simulation", "artifacts", "issues", "assumptions"):
            assert key in out, f"Missing key: {key}"

    def test_repaired_schemas_key_unwrapped(self):
        wrapped = {"repaired_schemas": CRM_SCHEMAS}
        out = check_execution_readiness({"schemas": wrapped})
        assert out["execution_score"] >= 60


# ─── Simulation Tests ─────────────────────────────────────────────────────────

class TestSimulateRuntime:
    def test_boot_log_not_empty(self):
        issues, assumptions = [], []
        sim = _simulate_runtime(CRM_SCHEMAS, issues, assumptions)
        assert len(sim["boot_log"]) >= 3

    def test_db_plan_counts(self):
        issues, assumptions = [], []
        sim = _simulate_runtime(CRM_SCHEMAS, issues, assumptions)
        assert len(sim["db_plan"]) == 3

    def test_all_tables_ddl_ready(self):
        issues, assumptions = [], []
        sim = _simulate_runtime(CRM_SCHEMAS, issues, assumptions)
        for t in sim["db_plan"]:
            assert t["ddl_ready"] is True, f"{t['table']} not DDL ready"

    def test_route_table_populated(self):
        issues, assumptions = [], []
        sim = _simulate_runtime(CRM_SCHEMAS, issues, assumptions)
        assert len(sim["route_table"]) >= 9

    def test_auth_matrix_has_two_roles(self):
        issues, assumptions = [], []
        sim = _simulate_runtime(CRM_SCHEMAS, issues, assumptions)
        roles = [r["role"] for r in sim["auth_matrix"]]
        assert "admin" in roles
        assert "user"  in roles

    def test_no_pk_raises_issue(self):
        issues, assumptions = [], []
        _simulate_runtime(NO_PK_SCHEMAS, issues, assumptions)
        assert any("primary key" in i.lower() for i in issues)

    def test_no_endpoints_raises_issue(self):
        issues, assumptions = [], []
        _simulate_runtime(NO_PK_SCHEMAS, issues, assumptions)
        assert any("endpoint" in i.lower() for i in issues)

    def test_health_check_assumption_added(self):
        # schemas without a /health endpoint should trigger assumption
        schemas = {
            "db_schema": CRM_SCHEMAS["db_schema"],
            "api_schema": {"endpoints": [{"method": "GET", "path": "/contacts", "auth_required": True}]},
            "ui_schema": CRM_SCHEMAS["ui_schema"],
            "auth_rules": CRM_SCHEMAS["auth_rules"],
        }
        issues, assumptions = [], []
        sim = _simulate_runtime(schemas, issues, assumptions)
        assert any("health" in a.lower() for a in assumptions)

    def test_no_roles_adds_assumption(self):
        schemas = dict(CRM_SCHEMAS)
        schemas["auth_rules"] = {"strategy": "jwt", "roles": [], "permissions": []}
        issues, assumptions = [], []
        _simulate_runtime(schemas, issues, assumptions)
        assert any("role" in a.lower() for a in assumptions)


# ─── Artifact Generation Tests ────────────────────────────────────────────────

class TestGenerateArtifacts:
    def test_sql_ddl_has_create_table(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        assert "CREATE TABLE" in arts["sql_ddl"]

    def test_sql_ddl_has_all_tables(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        for table in ("users", "contacts", "deals"):
            assert table in arts["sql_ddl"]

    def test_sql_ddl_has_fk_constraint(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        assert "CONSTRAINT fk_" in arts["sql_ddl"]

    def test_sql_ddl_has_begin_commit(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        assert "BEGIN;" in arts["sql_ddl"]
        assert "COMMIT;" in arts["sql_ddl"]

    def test_fastapi_has_router_decorator(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        assert "@router." in arts["fastapi_routes"]

    def test_fastapi_has_all_endpoints(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        for path in ("/auth/login", "/contacts", "/analytics"):
            assert path in arts["fastapi_routes"]

    def test_fastapi_has_require_role(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        assert "require_role" in arts["fastapi_routes"]

    def test_fastapi_has_health_endpoint(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        assert "/health" in arts["fastapi_routes"]

    def test_react_pages_generated(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        assert isinstance(arts["react_pages"], dict)
        assert len(arts["react_pages"]) == 4

    def test_react_pages_have_tsx_extension(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        for fn in arts["react_pages"].keys():
            assert fn.endswith(".tsx"), f"{fn} not a .tsx file"

    def test_react_auth_guard_injected(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        # Dashboard page is auth_required
        dashboard_code = arts["react_pages"].get("dashboard.tsx", "")
        assert "useAuth" in dashboard_code or "Navigate" in dashboard_code

    def test_docker_compose_has_api_and_db(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        dc = arts["docker_compose"]
        assert "api:" in dc
        assert "db:" in dc

    def test_docker_compose_mounts_schema_sql(self):
        arts = _generate_artifacts(CRM_SCHEMAS, [], [])
        assert "schema.sql" in arts["docker_compose"]

    def test_docker_compose_redis_for_session_auth(self):
        session_auth_schemas = dict(CRM_SCHEMAS)
        session_auth_schemas["auth_rules"] = {"strategy": "session", "roles": ["admin"]}
        arts = _generate_artifacts(session_auth_schemas, [], [])
        assert "redis:" in arts["docker_compose"]

    def test_empty_schemas_gives_placeholder_sql(self):
        arts = _generate_artifacts(EMPTY_SCHEMAS, [], [])
        assert "No tables defined" in arts["sql_ddl"]


# ─── Scoring Tests ────────────────────────────────────────────────────────────

class TestComputeScore:
    def test_full_crm_scores_high(self):
        issues, assumptions = [], []
        from pipeline.stage6_execution import _simulate_runtime, _generate_artifacts
        sim  = _simulate_runtime(CRM_SCHEMAS, issues, assumptions)
        arts = _generate_artifacts(CRM_SCHEMAS, issues, assumptions)
        score = _compute_score(CRM_SCHEMAS, sim, arts, issues)
        assert score >= 70

    def test_empty_schemas_scores_zero(self):
        issues = ["No tables", "No endpoints", "No pages"]
        score = _compute_score({}, {"db_plan": [], "route_table": [], "auth_matrix": []}, {}, issues)
        assert score == 0

    def test_issues_reduce_score(self):
        issues_none, issues_two = [], ["issue1", "issue2"]
        sim  = {"db_plan": [], "route_table": [], "auth_matrix": []}
        arts = {}
        s0 = _compute_score(CRM_SCHEMAS, sim, arts, issues_none)
        s2 = _compute_score(CRM_SCHEMAS, sim, arts, issues_two)
        assert s0 > s2
        assert s0 - s2 == 20  # 10 pts per issue
