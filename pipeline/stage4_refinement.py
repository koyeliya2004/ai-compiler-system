"""
Stage 4 — Refinement Layer
Cross-layer consistency enforcement.
"""
import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a strict schema consistency enforcer. Fix ALL cross-layer inconsistencies in the schemas JSON.
Return the FIXED schemas JSON with keys: ui_config, api_config, db_schema, auth_config.
Rules:
1. Every role in endpoint allowed_roles must exist in auth_config.roles
2. Every DB table must have an id primary key column
3. Endpoints that write data (POST/PUT/PATCH/DELETE) must have auth_required=true
4. Every UI page with auth_required=true must have at least one allowed_role
Output ONLY valid JSON. No markdown, no explanation.
"""


def refine_schemas(schemas: dict) -> dict:
    """Stage 4: Deterministic fixes + LLM cross-layer refinement."""
    from llm_client import chat_completion_json

    schemas = _deterministic_fixes(schemas)

    for attempt in range(3):
        try:
            result = chat_completion_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=f"Schemas:\n{json.dumps(schemas, indent=2)}",
                temperature=0.05
            )
            logger.info("[Stage4] Refinement complete")
            # Ensure we got all 4 keys back
            for key in ('ui_config', 'api_config', 'db_schema', 'auth_config'):
                if key not in result:
                    result[key] = schemas.get(key, {})
            return result
        except Exception as e:
            logger.warning(f"[Stage4] Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                logger.warning("[Stage4] Using deterministic-only fallback")
                return schemas


def _deterministic_fixes(schemas: dict) -> dict:
    auth_roles = set(schemas.get('auth_config', {}).get('roles', []))
    # Sync roles from endpoints → auth_config
    for ep in schemas.get('api_config', {}).get('endpoints', []):
        for role in ep.get('allowed_roles', []):
            if role and role not in auth_roles:
                schemas.setdefault('auth_config', {}).setdefault('roles', []).append(role)
                auth_roles.add(role)
    # Ensure id column in every table
    for table in schemas.get('db_schema', {}).get('tables', []):
        col_names = [c.get('name') for c in table.get('columns', [])]
        if 'id' not in col_names:
            table['columns'].insert(0, {'name': 'id', 'type': 'uuid', 'nullable': False, 'primary_key': True})
    return schemas
