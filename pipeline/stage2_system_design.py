"""
Stage 2: System Design Layer
============================
Converts IntentSchema → AppBlueprint.

This stage defines:
- Pages & routes (UI layer)
- API endpoints (with methods, auth, roles)
- Database tables & relations
- Auth system (JWT, roles, permissions)
- Business logic rules

Input:  IntentSchema (from Stage 1)
Output: AppBlueprint (validated JSON)
"""

import os
import json
import logging
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv
import jsonschema

load_dotenv()

logging.basicConfig(level=os.getenv("PIPELINE_LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_REPAIR_ATTEMPTS = int(os.getenv("MAX_REPAIR_ATTEMPTS", 3))

SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "app_blueprint_schema.json"
with open(SCHEMA_PATH) as f:
    APP_BLUEPRINT_SCHEMA = json.load(f)


SYSTEM_PROMPT = """
You are Stage 2 of an AI Compiler pipeline: System Design Layer.

Your job is to convert a validated IntentSchema into a complete AppBlueprint JSON.

Rules:
1. Output ONLY valid JSON — no markdown, no explanation, no code blocks.
2. ALL required fields must be present: app_name, pages, api_endpoints, database, auth, business_logic.
3. Every page must have: name, route, components (list), requires_auth (bool), roles_allowed (list).
4. Every API endpoint must have: path, method (GET/POST/PUT/PATCH/DELETE), description, request_body (or null), response (object), roles_allowed, auth_required.
5. Database tables must correspond to entities in the IntentSchema. Include id, created_at, updated_at on every table.
6. Auth type defaults to 'jwt'. Permissions map role names to list of allowed actions.
7. Business logic rules must reference real entities/roles from the IntentSchema.
8. API fields MUST match DB schema columns — no hallucinated fields.
9. UI components must map to real API endpoints.

AppBlueprint structure:
{
  "app_name": string,
  "pages": [{name, route, title, layout, components, requires_auth, roles_allowed}],
  "api_endpoints": [{path, method, description, request_body, response, roles_allowed, auth_required}],
  "database": {
    "type": "postgresql",
    "tables": [{name, columns: [{name, type, primary_key, nullable, unique, default}], relations}]
  },
  "auth": {"type": "jwt", "roles": [string], "permissions": {role: [action]}},
  "business_logic": [{name, description, trigger, action, conditions}]
}
"""


def design_system(intent_data: dict, repair_attempt: int = 0) -> dict:
    """
    Stage 2: Convert IntentSchema → AppBlueprint.

    Args:
        intent_data: Validated IntentSchema from Stage 1
        repair_attempt: Current repair attempt number

    Returns:
        Validated AppBlueprint dict
    """
    logger.info(f"[Stage 2] Designing system architecture (attempt {repair_attempt + 1})")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Convert this IntentSchema into an AppBlueprint JSON:\n\n{json.dumps(intent_data, indent=2)}"
        }
    ]

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.1,
        response_format={"type": "json_object"}
    )

    raw_output = response.choices[0].message.content
    logger.debug(f"[Stage 2] Raw LLM output (first 200 chars): {raw_output[:200]}...")

    try:
        blueprint = json.loads(raw_output)
    except json.JSONDecodeError as e:
        logger.error(f"[Stage 2] JSON parse error: {e}")
        if repair_attempt < MAX_REPAIR_ATTEMPTS:
            return _repair_blueprint(intent_data, raw_output, str(e), repair_attempt)
        raise ValueError(f"Stage 2 failed: Invalid JSON after {MAX_REPAIR_ATTEMPTS} attempts")

    errors = validate_blueprint_schema(blueprint)
    if errors:
        logger.warning(f"[Stage 2] Schema validation errors: {errors}")
        if repair_attempt < MAX_REPAIR_ATTEMPTS:
            return _repair_blueprint(intent_data, raw_output, str(errors), repair_attempt)
        raise ValueError(f"Stage 2 failed: Schema validation after {MAX_REPAIR_ATTEMPTS} attempts")

    # Cross-layer consistency check
    consistency_errors = check_cross_layer_consistency(intent_data, blueprint)
    if consistency_errors:
        logger.warning(f"[Stage 2] Cross-layer inconsistencies: {consistency_errors}")
        if repair_attempt < MAX_REPAIR_ATTEMPTS:
            return _repair_blueprint(intent_data, raw_output, str(consistency_errors), repair_attempt)
        logger.warning("[Stage 2] Proceeding with inconsistencies (will be resolved in Stage 4)")

    logger.info(f"[Stage 2] ✅ AppBlueprint generated: {len(blueprint.get('pages', []))} pages, "
                f"{len(blueprint.get('api_endpoints', []))} endpoints, "
                f"{len(blueprint.get('database', {}).get('tables', []))} tables")
    return blueprint


def _repair_blueprint(intent_data: dict, bad_output: str, error: str, attempt: int) -> dict:
    """Targeted repair for AppBlueprint generation failures."""
    logger.info(f"[Stage 2] 🔧 Repairing blueprint (attempt {attempt + 1}/{MAX_REPAIR_ATTEMPTS})")

    repair_prompt = f"""You previously generated this AppBlueprint JSON:
{bad_output}

It failed with this error:
{error}

Fix ONLY the issues above. Return valid JSON conforming to AppBlueprint schema.
The original IntentSchema was:
{json.dumps(intent_data, indent=2)}"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": repair_prompt}
        ],
        temperature=0.05,
        response_format={"type": "json_object"}
    )

    repaired = response.choices[0].message.content
    try:
        data = json.loads(repaired)
    except json.JSONDecodeError as e:
        if attempt + 1 < MAX_REPAIR_ATTEMPTS:
            return _repair_blueprint(intent_data, repaired, str(e), attempt + 1)
        raise ValueError(f"Stage 2 repair failed: {e}")

    errors = validate_blueprint_schema(data)
    if errors:
        if attempt + 1 < MAX_REPAIR_ATTEMPTS:
            return _repair_blueprint(intent_data, repaired, str(errors), attempt + 1)
        raise ValueError(f"Stage 2 repair failed after {attempt + 1} attempts")

    logger.info("[Stage 2] ✅ Repair successful")
    return data


def validate_blueprint_schema(data: dict) -> list:
    """Validate AppBlueprint against JSON Schema contract."""
    validator = jsonschema.Draft7Validator(APP_BLUEPRINT_SCHEMA)
    return [str(e.message) for e in validator.iter_errors(data)]


def check_cross_layer_consistency(intent: dict, blueprint: dict) -> list:
    """
    Cross-layer consistency checks:
    - All intent entities must appear as DB tables
    - All intent roles must appear in auth.roles
    - API endpoint roles must be a subset of defined roles
    - UI pages with requires_auth must have roles_allowed populated
    """
    errors = []
    defined_roles = set(blueprint.get("auth", {}).get("roles", []))
    db_tables = {t["name"].lower() for t in blueprint.get("database", {}).get("tables", [])}
    intent_entities = {e["name"].lower() for e in intent.get("entities", [])}
    intent_roles = {r["name"].lower() for r in intent.get("roles", [])}

    # Check all intent entities are represented in DB
    missing_tables = intent_entities - db_tables
    if missing_tables:
        errors.append(f"Missing DB tables for entities: {missing_tables}")

    # Check all intent roles exist in auth
    missing_roles = intent_roles - {r.lower() for r in defined_roles}
    if missing_roles:
        errors.append(f"Intent roles not in auth.roles: {missing_roles}")

    # Check API endpoint roles are defined
    for ep in blueprint.get("api_endpoints", []):
        for role in ep.get("roles_allowed", []):
            if role.lower() not in {r.lower() for r in defined_roles}:
                errors.append(f"Endpoint {ep['path']} references undefined role: {role}")

    # Check pages with requires_auth have roles_allowed
    for page in blueprint.get("pages", []):
        if page.get("requires_auth") and not page.get("roles_allowed"):
            errors.append(f"Page '{page['name']}' requires_auth but has no roles_allowed")

    return errors


if __name__ == "__main__":
    # Demo: Use a sample IntentSchema to generate AppBlueprint
    sample_intent = {
        "app_name": "CRM Pro",
        "app_type": "CRM",
        "description": "A CRM with contacts, dashboard, role-based access, and premium payments",
        "features": [
            {"name": "Login", "description": "User authentication", "priority": "must-have", "requires_auth": False, "roles_allowed": []},
            {"name": "Contacts", "description": "Manage contacts", "priority": "must-have", "requires_auth": True, "roles_allowed": ["user", "admin"]},
            {"name": "Dashboard", "description": "Overview metrics", "priority": "must-have", "requires_auth": True, "roles_allowed": ["user", "admin"]},
            {"name": "Analytics", "description": "Advanced analytics for admins", "priority": "must-have", "requires_auth": True, "roles_allowed": ["admin"]},
            {"name": "Premium Plan", "description": "Stripe payments for premium", "priority": "must-have", "requires_auth": True, "roles_allowed": ["user", "admin"]}
        ],
        "entities": [
            {"name": "User", "fields": [{"name": "id", "type": "uuid", "required": True, "unique": True}, {"name": "email", "type": "email", "required": True, "unique": True}, {"name": "role", "type": "string", "required": True, "unique": False}]},
            {"name": "Contact", "fields": [{"name": "id", "type": "uuid", "required": True, "unique": True}, {"name": "name", "type": "string", "required": True, "unique": False}, {"name": "email", "type": "email", "required": True, "unique": False}]}
        ],
        "roles": [
            {"name": "user", "permissions": ["read:contacts", "write:contacts"], "is_default": True},
            {"name": "admin", "permissions": ["read:contacts", "write:contacts", "read:analytics", "manage:users"], "is_default": False}
        ],
        "auth_required": True,
        "payment_required": True,
        "premium_features": ["Analytics", "Advanced Reports"],
        "assumptions": ["Using Stripe for payments", "PostgreSQL for database"],
        "clarifications_needed": []
    }

    print("=" * 60)
    print("AI COMPILER — Stage 2: System Design Layer")
    print("=" * 60)

    blueprint = design_system(sample_intent)
    print("\n📋 App Blueprint:")
    print(json.dumps(blueprint, indent=2))
