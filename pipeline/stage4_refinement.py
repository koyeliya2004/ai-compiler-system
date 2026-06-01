"""
Stage 4 — Refinement Layer
Resolves cross-layer inconsistencies in the generated schemas.
Checks:
  - API fields match DB columns
  - UI routes match API endpoints
  - Auth roles are consistent across all layers
  - Missing required fields are filled with sensible defaults
"""
import os
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a strict schema consistency enforcer. Given schemas JSON with ui_config, api_config, db_schema, auth_config,
identify and fix ALL cross-layer inconsistencies.

Rules to enforce:
1. Every API endpoint path must be reachable from a UI page
2. Every db table column used in an API response_schema must exist in the db table
3. Every role in api_config allowed_roles must exist in auth_config.roles
4. Every UI page with auth_required=true must have allowed_roles that exist in auth_config.roles
5. All tables must have an id primary key column
6. Endpoints that modify data (POST/PUT/PATCH/DELETE) must have auth_required=true

Return the FIXED schemas JSON with the SAME structure. Output ONLY valid JSON. No markdown, no explanation.
"""


def refine_schemas(schemas: dict) -> dict:
    """Stage 4: Cross-layer refinement."""
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    # First do deterministic rule-based fixes
    schemas = _deterministic_fixes(schemas)

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.05,
                max_tokens=4096,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Schemas:\n{json.dumps(schemas, indent=2)}"}
                ]
            )
            refined = json.loads(resp.choices[0].message.content)
            logger.info("[Stage4] Refinement complete")
            return refined
        except Exception as e:
            logger.warning(f"[Stage4] Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                logger.warning("[Stage4] Using deterministic-only fixes as fallback")
                return schemas  # Return deterministic fixes as fallback


def _deterministic_fixes(schemas: dict) -> dict:
    """Rule-based consistency fixes that don't need an LLM."""
    # Ensure auth roles are consistent
    auth_roles = set(schemas.get("auth_config", {}).get("roles", []))

    # Fix API endpoints: add missing roles to auth_config
    for ep in schemas.get("api_config", {}).get("endpoints", []):
        for role in ep.get("allowed_roles", []):
            if role not in auth_roles:
                schemas.setdefault("auth_config", {}).setdefault("roles", []).append(role)
                auth_roles.add(role)

    # Fix DB tables: ensure id column exists
    for table in schemas.get("db_schema", {}).get("tables", []):
        col_names = [c["name"] for c in table.get("columns", [])]
        if "id" not in col_names:
            table["columns"].insert(0, {"name": "id", "type": "uuid", "nullable": False, "primary_key": True})

    return schemas
