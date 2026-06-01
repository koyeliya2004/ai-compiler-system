"""
Stage 4: Refinement Layer
===========================
Resolves cross-layer inconsistencies in the generated schemas.

Checks and fixes:
- API paths referenced in UI but missing from api_config
- DB columns referenced in API but missing from db_schema
- Route guards missing for UI pages
- Role mismatches across layers

Input:  raw schemas dict (output of Stage 3)
Output: refined schemas dict
"""

import os
import json
import logging
from copy import deepcopy
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.getenv('PIPELINE_LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 4 of an AI Compiler pipeline — the Refinement Layer.

You receive 4 schemas (ui_config, api_config, db_schema, auth_config) and a list of
cross-layer inconsistencies detected by the validator.

Your job: fix ONLY the listed inconsistencies. Do not change anything else.

Return the complete corrected schemas as valid JSON with all 4 keys.
No explanation, no markdown. Just the fixed JSON.
"""


def _find_inconsistencies(schemas: dict) -> list:
    """Detect cross-layer inconsistencies before LLM refinement."""
    issues = []
    ui = schemas.get('ui_config', {})
    api = schemas.get('api_config', {})
    db = schemas.get('db_schema', {})
    auth = schemas.get('auth_config', {})

    api_paths = {ep.get('path') for ep in api.get('endpoints', [])}
    db_cols = set()
    for table in db.get('tables', []):
        for col in table.get('columns', []):
            db_cols.add(f"{table['name']}.{col['name']}")
    guard_routes = {g.get('route') for g in auth.get('route_guards', [])}
    auth_roles = {r.get('name') for r in auth.get('roles', [])}

    for page in ui.get('pages', []):
        if page.get('route') not in guard_routes:
            issues.append(f"Page '{page.get('route')}' has no route guard")
        for role in page.get('roles_allowed', []):
            if role not in auth_roles:
                issues.append(f"Role '{role}' in page '{page.get('route')}' not in auth_config.roles")
        for comp in page.get('components', []):
            bound = comp.get('binds_to_api', '')
            if bound and bound not in api_paths:
                issues.append(f"Component '{comp.get('id')}' binds to missing API: {bound}")

    for ep in api.get('endpoints', []):
        rb = ep.get('request_body')
        if isinstance(rb, dict):
            for field in rb.get('fields', []):
                ref = field.get('maps_to_db', '')
                if ref and ref not in db_cols:
                    issues.append(f"API field maps to missing DB column: {ref}")

    return issues


def refine_schemas(schemas: dict, max_retries: int = 2) -> dict:
    """
    Stage 4: Detect and fix cross-layer inconsistencies.
    Uses LLM only if inconsistencies are found.
    """
    from llm_client import chat_completion_json

    issues = _find_inconsistencies(schemas)

    if not issues:
        logger.info('[Stage 4] ✅ No inconsistencies found — schemas are consistent')
        return schemas

    logger.warning(f'[Stage 4] Found {len(issues)} inconsistency(ies): {issues}')

    schemas_str = json.dumps(schemas, indent=2)
    issues_str = '\n'.join(f'- {i}' for i in issues)

    for attempt in range(max_retries + 1):
        try:
            logger.info(f'[Stage 4] Refining schemas (attempt {attempt + 1})')
            result = chat_completion_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=f'Schemas:\n{schemas_str}\n\nInconsistencies to fix:\n{issues_str}',
                temperature=0.05,
                max_tokens=8192
            )

            required_keys = {'ui_config', 'api_config', 'db_schema', 'auth_config'}
            missing = required_keys - set(result.keys())
            if not missing:
                remaining = _find_inconsistencies(result)
                if not remaining:
                    logger.info('[Stage 4] ✅ All inconsistencies resolved')
                else:
                    logger.warning(f'[Stage 4] {len(remaining)} inconsistencies remain after refinement')
                return result

            logger.warning(f'[Stage 4] Missing keys after refinement: {missing}')

        except Exception as e:
            logger.error(f'[Stage 4] Error on attempt {attempt + 1}: {e}')
            if attempt == max_retries:
                logger.warning('[Stage 4] Returning original schemas after failed refinement')
                return schemas

    return schemas


if __name__ == '__main__':
    print('[Stage 4] Import refine_schemas(schemas) from this module.')
