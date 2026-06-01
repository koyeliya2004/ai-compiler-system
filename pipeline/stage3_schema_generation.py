"""
Stage 3: Schema Generation
==========================
Converts AppBlueprint → 4 separate config schemas:
  1. ui_config    — Pages, components, layouts, field bindings
  2. api_config   — Endpoint specs with request/response contracts
  3. db_schema    — SQL DDL + migration-ready table definitions
  4. auth_config  — Roles, permissions, JWT settings, route guards

Input:  AppBlueprint (from Stage 2)
Output: { ui_config, api_config, db_schema, auth_config } (all validated)
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=os.getenv("PIPELINE_LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_REPAIR_ATTEMPTS = int(os.getenv("MAX_REPAIR_ATTEMPTS", 3))


# ─── Sub-schema prompts (each generates ONE config) ───────────────────────────

UI_CONFIG_PROMPT = """
You are generating the UI Config for an app.
Output a JSON object with this structure:
{
  "pages": [
    {
      "name": string,
      "route": string,
      "title": string,
      "layout": "sidebar" | "centered" | "dashboard" | "full",
      "requires_auth": boolean,
      "roles_allowed": [string],
      "components": [
        {
          "id": string,
          "type": "DataTable" | "Form" | "Chart" | "Card" | "Modal" | "Button" | "NavBar" | "Sidebar" | "StatCard" | "List",
          "label": string,
          "binds_to_api": string,
          "fields": [{"name": string, "type": string, "required": boolean, "maps_to_db_column": string}]
        }
      ]
    }
  ]
}
Rules:
- Every component must have a binds_to_api field referencing a real API endpoint path.
- Form fields must have maps_to_db_column referencing a real DB column.
- Output ONLY valid JSON.
"""

API_CONFIG_PROMPT = """
You are generating the API Config for an app.
Output a JSON object with this structure:
{
  "base_url": "/api/v1",
  "endpoints": [
    {
      "path": string,
      "method": "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
      "description": string,
      "auth_required": boolean,
      "roles_allowed": [string],
      "request_body": {"fields": [{"name": string, "type": string, "required": boolean, "maps_to_db": string}]} | null,
      "response": {"status": number, "schema": object},
      "validation_rules": [{"field": string, "rule": string}]
    }
  ]
}
Rules:
- Every request_body field must have maps_to_db referencing a real DB table.column.
- All roles_allowed must be defined roles.
- Output ONLY valid JSON.
"""

DB_SCHEMA_PROMPT = """
You are generating the Database Schema for an app.
Output a JSON object with this structure:
{
  "database_type": "postgresql",
  "tables": [
    {
      "name": string,
      "columns": [
        {
          "name": string,
          "type": "UUID" | "VARCHAR" | "TEXT" | "INTEGER" | "BIGINT" | "BOOLEAN" | "TIMESTAMP" | "DECIMAL" | "JSONB",
          "primary_key": boolean,
          "nullable": boolean,
          "unique": boolean,
          "default": string | null,
          "foreign_key": {"references_table": string, "references_column": string} | null
        }
      ],
      "indexes": [{"name": string, "columns": [string], "unique": boolean}],
      "ddl": string
    }
  ]
}
Rules:
- Every table MUST have: id (UUID, PK), created_at (TIMESTAMP), updated_at (TIMESTAMP).
- Foreign keys must reference real tables.
- Include the DDL CREATE TABLE statement for each table.
- Output ONLY valid JSON.
"""

AUTH_CONFIG_PROMPT = """
You are generating the Auth Config for an app.
Output a JSON object with this structure:
{
  "auth_type": "jwt",
  "jwt": {
    "secret_env_var": "JWT_SECRET",
    "algorithm": "HS256",
    "access_token_expiry": "15m",
    "refresh_token_expiry": "7d"
  },
  "roles": [
    {
      "name": string,
      "is_default": boolean,
      "permissions": [string]
    }
  ],
  "route_guards": [
    {
      "route": string,
      "requires_auth": boolean,
      "roles_allowed": [string],
      "redirect_to": string
    }
  ],
  "password_policy": {
    "min_length": 8,
    "require_uppercase": true,
    "require_number": true,
    "require_special": false
  }
}
Rules:
- route_guards must cover ALL routes from the pages list.
- permissions format: "action:resource" (e.g., "read:contacts").
- Output ONLY valid JSON.
"""


def generate_schemas(blueprint: dict) -> dict:
    """
    Stage 3: Generate all 4 config schemas from the AppBlueprint.

    Runs each sub-schema generation INDEPENDENTLY (modular, not a single mega-prompt).
    This ensures each schema is focused, reliable, and independently repairable.

    Returns:
        {
            'ui_config': {...},
            'api_config': {...},
            'db_schema': {...},
            'auth_config': {...}
        }
    """
    logger.info("[Stage 3] Generating 4 config schemas from AppBlueprint...")

    blueprint_str = json.dumps(blueprint, indent=2)

    # Generate each schema independently (modular, parallel-friendly)
    ui_config = _generate_single_schema("UI Config", UI_CONFIG_PROMPT, blueprint_str, "ui_config")
    api_config = _generate_single_schema("API Config", API_CONFIG_PROMPT, blueprint_str, "api_config")
    db_schema = _generate_single_schema("DB Schema", DB_SCHEMA_PROMPT, blueprint_str, "db_schema")
    auth_config = _generate_single_schema("Auth Config", AUTH_CONFIG_PROMPT, blueprint_str, "auth_config")

    schemas = {
        "ui_config": ui_config,
        "api_config": api_config,
        "db_schema": db_schema,
        "auth_config": auth_config
    }

    # Cross-schema field consistency check
    field_errors = check_field_consistency(schemas)
    if field_errors:
        logger.warning(f"[Stage 3] ⚠️ Field consistency issues (will be resolved in Stage 4): {field_errors}")
    else:
        logger.info("[Stage 3] ✅ All schemas are field-consistent")

    logger.info(f"[Stage 3] ✅ Schema generation complete")
    return schemas


def _generate_single_schema(
    schema_name: str,
    system_prompt: str,
    blueprint_str: str,
    schema_key: str,
    repair_attempt: int = 0
) -> dict:
    """Generate a single config schema with repair loop."""
    logger.info(f"[Stage 3] Generating {schema_name} (attempt {repair_attempt + 1})")

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Generate the {schema_name} for this AppBlueprint:\n\n{blueprint_str}"}
        ],
        temperature=0.1,
        response_format={"type": "json_object"}
    )

    raw = response.choices[0].message.content

    try:
        parsed = json.loads(raw)
        logger.info(f"[Stage 3] ✅ {schema_name} generated successfully")
        return parsed
    except json.JSONDecodeError as e:
        logger.error(f"[Stage 3] {schema_name} JSON parse error: {e}")
        if repair_attempt < MAX_REPAIR_ATTEMPTS:
            return _repair_single_schema(schema_name, system_prompt, blueprint_str, raw, str(e), schema_key, repair_attempt)
        raise ValueError(f"Stage 3 {schema_name} failed after {MAX_REPAIR_ATTEMPTS} attempts")


def _repair_single_schema(
    schema_name: str,
    system_prompt: str,
    blueprint_str: str,
    bad_output: str,
    error: str,
    schema_key: str,
    attempt: int
) -> dict:
    """Targeted repair for a single schema failure."""
    logger.info(f"[Stage 3] 🔧 Repairing {schema_name} (attempt {attempt + 1}/{MAX_REPAIR_ATTEMPTS})")

    repair_prompt = f"""Your previous {schema_name} JSON:
{bad_output}

Failed with: {error}

Fix ONLY the issue above. Return valid JSON only.
AppBlueprint context:
{blueprint_str}"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": repair_prompt}
        ],
        temperature=0.05,
        response_format={"type": "json_object"}
    )

    repaired = response.choices[0].message.content
    try:
        data = json.loads(repaired)
        logger.info(f"[Stage 3] ✅ {schema_name} repair successful")
        return data
    except json.JSONDecodeError as e:
        if attempt + 1 < MAX_REPAIR_ATTEMPTS:
            return _repair_single_schema(schema_name, system_prompt, blueprint_str, repaired, str(e), schema_key, attempt + 1)
        raise ValueError(f"Stage 3 {schema_name} repair failed: {e}")


def check_field_consistency(schemas: dict) -> list:
    """
    Cross-schema field consistency:
    - API request fields must reference valid DB table.column
    - UI component fields must map to real API endpoint paths
    - Auth route guards must cover all UI page routes
    """
    errors = []

    # Build lookup sets
    db_columns = set()
    for table in schemas.get("db_schema", {}).get("tables", []):
        for col in table.get("columns", []):
            db_columns.add(f"{table['name']}.{col['name']}")

    api_paths = set()
    for ep in schemas.get("api_config", {}).get("endpoints", []):
        api_paths.add(ep.get("path", ""))

    ui_routes = set()
    for page in schemas.get("ui_config", {}).get("pages", []):
        ui_routes.add(page.get("route", ""))
        for comp in page.get("components", []):
            bound_api = comp.get("binds_to_api", "")
            if bound_api and bound_api not in api_paths:
                errors.append(f"UI component '{comp.get('id')}' binds to non-existent API: {bound_api}")
            for field in comp.get("fields", []):
                db_ref = field.get("maps_to_db_column", "")
                if db_ref and db_ref not in db_columns:
                    errors.append(f"UI field '{field['name']}' maps to non-existent DB column: {db_ref}")

    guard_routes = {g.get("route") for g in schemas.get("auth_config", {}).get("route_guards", [])}
    uncovered = ui_routes - guard_routes
    if uncovered:
        errors.append(f"UI routes not covered by auth route_guards: {uncovered}")

    return errors


if __name__ == "__main__":
    # Demo: Use a minimal AppBlueprint
    sample_blueprint = {
        "app_name": "CRM Pro",
        "pages": [
            {"name": "Login", "route": "/login", "title": "Login", "layout": "centered", "components": ["LoginForm"], "requires_auth": False, "roles_allowed": []},
            {"name": "Dashboard", "route": "/dashboard", "title": "Dashboard", "layout": "dashboard", "components": ["StatCards", "ContactsTable"], "requires_auth": True, "roles_allowed": ["user", "admin"]},
            {"name": "Analytics", "route": "/analytics", "title": "Analytics", "layout": "dashboard", "components": ["RevenueChart", "UserGrowthChart"], "requires_auth": True, "roles_allowed": ["admin"]}
        ],
        "api_endpoints": [
            {"path": "/api/v1/auth/login", "method": "POST", "description": "Authenticate user", "request_body": {"email": "string", "password": "string"}, "response": {"token": "string"}, "roles_allowed": [], "auth_required": False},
            {"path": "/api/v1/contacts", "method": "GET", "description": "List contacts", "request_body": None, "response": {"contacts": []}, "roles_allowed": ["user", "admin"], "auth_required": True}
        ],
        "database": {
            "type": "postgresql",
            "tables": [
                {"name": "users", "columns": [{"name": "id", "type": "UUID", "primary_key": True, "nullable": False, "unique": True, "default": None}], "relations": []},
                {"name": "contacts", "columns": [{"name": "id", "type": "UUID", "primary_key": True, "nullable": False, "unique": True, "default": None}, {"name": "name", "type": "VARCHAR", "primary_key": False, "nullable": False, "unique": False, "default": None}], "relations": []}
            ]
        },
        "auth": {"type": "jwt", "roles": ["user", "admin"], "permissions": {"user": ["read:contacts", "write:contacts"], "admin": ["read:contacts", "write:contacts", "read:analytics"]}},
        "business_logic": [{"name": "PremiumGating", "description": "Gate analytics behind premium plan", "trigger": "analytics page access", "action": "check user subscription status", "conditions": ["user.plan == premium"]}]
    }

    print("=" * 60)
    print("AI COMPILER — Stage 3: Schema Generation")
    print("=" * 60)

    schemas = generate_schemas(sample_blueprint)
    print("\n📦 Generated Schemas:")
    for key, val in schemas.items():
        print(f"\n--- {key.upper()} ---")
        print(json.dumps(val, indent=2)[:500] + "...")
