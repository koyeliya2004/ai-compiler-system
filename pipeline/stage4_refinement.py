"""
Stage 4: Refinement Layer
=========================
Resolves all cross-layer inconsistencies across the 4 generated schemas.

Checks and fixes:
- API fields not matching DB columns → align them
- UI bindings pointing to non-existent API paths → correct them
- Auth route guards missing for UI pages → add them
- Role references that don't exist in auth → remove/correct them
- DB foreign keys referencing non-existent tables → fix them

Input:  { ui_config, api_config, db_schema, auth_config } from Stage 3
Output: Refined, consistent { ui_config, api_config, db_schema, auth_config }
"""

import os
import json
import logging

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=os.getenv("PIPELINE_LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_REPAIR_ATTEMPTS = int(os.getenv("MAX_REPAIR_ATTEMPTS", 3))


def refine_schemas(schemas: dict, repair_attempt: int = 0) -> dict:
    """
    Stage 4: Resolve all cross-layer inconsistencies.

    Strategy:
    1. Run deterministic consistency checks (no LLM needed for simple fixes)
    2. For complex semantic inconsistencies, use LLM with targeted prompt
    3. Re-validate after refinement

    Returns: Refined schemas dict
    """
    logger.info(f"[Stage 4] Refining schemas for cross-layer consistency (attempt {repair_attempt + 1})")

    # Step 1: Deterministic fixes (fast, no LLM cost)
    schemas = _deterministic_fixes(schemas)

    # Step 2: Detect remaining issues
    issues = detect_all_inconsistencies(schemas)

    if not issues:
        logger.info("[Stage 4] ✅ No inconsistencies found — schemas are consistent")
        return schemas

    logger.warning(f"[Stage 4] Found {len(issues)} inconsistencies, running LLM refinement...")

    # Step 3: LLM-based refinement for complex issues
    refined = _llm_refine(schemas, issues, repair_attempt)

    # Step 4: Final consistency check
    remaining = detect_all_inconsistencies(refined)
    if remaining:
        logger.warning(f"[Stage 4] ⚠️ {len(remaining)} issues remain after refinement: {remaining[:3]}")
    else:
        logger.info("[Stage 4] ✅ All inconsistencies resolved")

    return refined


def _deterministic_fixes(schemas: dict) -> dict:
    """
    Fast deterministic fixes without LLM:
    - Add missing auth route guards for all UI pages
    - Remove endpoint roles that aren't in auth.roles
    - Add missing standard DB columns (id, created_at, updated_at)
    """
    defined_roles = set(r["name"] for r in schemas.get("auth_config", {}).get("roles", []))
    guard_routes = {g["route"] for g in schemas.get("auth_config", {}).get("route_guards", [])}
    ui_pages = schemas.get("ui_config", {}).get("pages", [])

    # Fix 1: Add missing route guards
    for page in ui_pages:
        if page["route"] not in guard_routes:
            schemas["auth_config"].setdefault("route_guards", []).append({
                "route": page["route"],
                "requires_auth": page.get("requires_auth", False),
                "roles_allowed": page.get("roles_allowed", []),
                "redirect_to": "/login"
            })
            logger.info(f"[Stage 4] 🔧 Added missing route guard for {page['route']}")

    # Fix 2: Remove undefined roles from API endpoints
    for ep in schemas.get("api_config", {}).get("endpoints", []):
        original_roles = ep.get("roles_allowed", [])
        valid_roles = [r for r in original_roles if r in defined_roles]
        if len(valid_roles) != len(original_roles):
            removed = set(original_roles) - set(valid_roles)
            logger.info(f"[Stage 4] 🔧 Removed undefined roles from {ep['path']}: {removed}")
            ep["roles_allowed"] = valid_roles

    # Fix 3: Ensure every DB table has standard columns
    standard_cols = {
        "id": {"name": "id", "type": "UUID", "primary_key": True, "nullable": False, "unique": True, "default": "gen_random_uuid()", "foreign_key": None},
        "created_at": {"name": "created_at", "type": "TIMESTAMP", "primary_key": False, "nullable": False, "unique": False, "default": "NOW()", "foreign_key": None},
        "updated_at": {"name": "updated_at", "type": "TIMESTAMP", "primary_key": False, "nullable": False, "unique": False, "default": "NOW()", "foreign_key": None}
    }
    for table in schemas.get("db_schema", {}).get("tables", []):
        existing_cols = {c["name"] for c in table.get("columns", [])}
        for col_name, col_def in standard_cols.items():
            if col_name not in existing_cols:
                table["columns"].insert(0 if col_name == "id" else len(table["columns"]), col_def)
                logger.info(f"[Stage 4] 🔧 Added missing '{col_name}' to table '{table['name']}'")

    return schemas


def _llm_refine(schemas: dict, issues: list, attempt: int) -> dict:
    """Use LLM to resolve complex semantic inconsistencies."""
    issues_str = "\n".join(f"- {i}" for i in issues[:10])  # Cap at 10 to avoid token explosion

    prompt = f"""You are Stage 4 of an AI Compiler: Refinement Layer.

The following cross-layer inconsistencies were detected:
{issues_str}

Here are the current schemas:
{json.dumps(schemas, indent=2)}

Fix ALL the listed inconsistencies. Rules:
1. Do NOT change things that are already correct.
2. API fields must match DB schema columns.
3. UI bindings must point to real API paths.
4. All role references must match auth.roles.
5. Return the complete, fixed schemas as a single JSON object with keys: ui_config, api_config, db_schema, auth_config.
6. Output ONLY valid JSON."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.05,
        response_format={"type": "json_object"}
    )

    try:
        refined = json.loads(response.choices[0].message.content)
        # Ensure all 4 keys are present
        for key in ["ui_config", "api_config", "db_schema", "auth_config"]:
            if key not in refined:
                refined[key] = schemas[key]  # Fall back to original if missing
        return refined
    except json.JSONDecodeError as e:
        logger.error(f"[Stage 4] LLM refinement parse error: {e}")
        if attempt < MAX_REPAIR_ATTEMPTS:
            return _llm_refine(schemas, issues, attempt + 1)
        logger.warning("[Stage 4] LLM refinement failed, returning partially fixed schemas")
        return schemas


def detect_all_inconsistencies(schemas: dict) -> list:
    """
    Comprehensive cross-layer consistency detection.
    Returns list of human-readable issue descriptions.
    """
    issues = []

    # Build lookup sets
    db_tables = {t["name"]: t for t in schemas.get("db_schema", {}).get("tables", [])}
    db_columns = set()
    for table in db_tables.values():
        for col in table.get("columns", []):
            db_columns.add(f"{table['name']}.{col['name']}")

    api_paths = {ep["path"] for ep in schemas.get("api_config", {}).get("endpoints", [])}
    defined_roles = {r["name"] for r in schemas.get("auth_config", {}).get("roles", [])}
    guard_routes = {g["route"] for g in schemas.get("auth_config", {}).get("route_guards", [])}
    ui_routes = {p["route"] for p in schemas.get("ui_config", {}).get("pages", [])}

    # Check 1: UI bindings → API paths
    for page in schemas.get("ui_config", {}).get("pages", []):
        for comp in page.get("components", []):
            bound = comp.get("binds_to_api", "")
            if bound and bound not in api_paths:
                issues.append(f"UI '{comp.get('id')}' binds to non-existent API path: {bound}")
            for field in comp.get("fields", []):
                db_ref = field.get("maps_to_db_column", "")
                if db_ref and db_ref not in db_columns:
                    issues.append(f"UI field '{field['name']}' maps to non-existent DB: {db_ref}")

    # Check 2: API request fields → DB columns
    for ep in schemas.get("api_config", {}).get("endpoints", []):
        rb = ep.get("request_body")
        if rb and isinstance(rb, dict):
            for f in rb.get("fields", []):
                db_ref = f.get("maps_to_db", "")
                if db_ref and db_ref not in db_columns:
                    issues.append(f"API {ep['path']} field '{f['name']}' maps to non-existent DB: {db_ref}")
        for role in ep.get("roles_allowed", []):
            if role not in defined_roles:
                issues.append(f"API {ep['path']} references undefined role: {role}")

    # Check 3: DB foreign keys → real tables
    for table in db_tables.values():
        for col in table.get("columns", []):
            fk = col.get("foreign_key")
            if fk and fk.get("references_table") not in db_tables:
                issues.append(f"DB {table['name']}.{col['name']} FK references non-existent table: {fk['references_table']}")

    # Check 4: Auth route guards cover all UI routes
    uncovered = ui_routes - guard_routes
    for route in uncovered:
        issues.append(f"UI route '{route}' has no auth route guard")

    return issues


if __name__ == "__main__":
    print("Stage 4: Refinement Layer — run after Stage 3 output is available")
    print("Import and call: refine_schemas(schemas_from_stage3)")
