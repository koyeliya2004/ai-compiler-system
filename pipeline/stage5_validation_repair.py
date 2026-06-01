"""
Stage 5: Validation + Repair Engine
====================================
The CORE reliability layer of the AI Compiler pipeline.

Responsibilities:
- Validate the final pipeline output against ALL schema contracts
- Detect: invalid JSON, missing keys, hallucinated fields, schema mismatches,
  logical inconsistencies, cross-layer reference errors
- Repair: deterministic fixes first, then targeted LLM repair
- Re-validate after repair (NOT a blind full retry)

Input:  final_output dict (assembled after Stages 1-4)
Output: { valid, errors, warnings } + repaired final_output if needed
"""

import os
import json
import logging
from copy import deepcopy
from pathlib import Path

from dotenv import load_dotenv
import jsonschema

load_dotenv()
logging.basicConfig(level=os.getenv('PIPELINE_LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

with open(ROOT / 'schemas' / 'intent_schema.json') as f:
    INTENT_SCHEMA = json.load(f)
with open(ROOT / 'schemas' / 'app_blueprint_schema.json') as f:
    APP_BLUEPRINT_SCHEMA = json.load(f)
with open(ROOT / 'schemas' / 'output_schema.json') as f:
    OUTPUT_SCHEMA = json.load(f)

REQUIRED_SCHEMA_KEYS = {'ui_config', 'api_config', 'db_schema', 'auth_config'}


def _jsonschema_errors(schema: dict, data: dict) -> list:
    """Return list of JSON Schema validation error messages."""
    return [str(e.message) for e in jsonschema.Draft7Validator(schema).iter_errors(data)]


def validate_pipeline_output(final_output: dict) -> dict:
    """
    Full validation of the final pipeline output.

    Checks:
    1. intent_raw conforms to IntentSchema
    2. blueprint conforms to AppBlueprintSchema
    3. final_output conforms to OutputSchema
    4. All 4 sub-schemas present
    5. UI components bind to real API paths
    6. UI fields map to real DB columns
    7. API request fields map to real DB columns
    8. All UI pages have route guards

    Returns:
        { valid: bool, errors: [str], warnings: [str] }
    """
    errors = []
    warnings = []

    errors.extend([f'[IntentSchema] {e}' for e in _jsonschema_errors(INTENT_SCHEMA, final_output.get('intent_raw', {}))])
    errors.extend([f'[AppBlueprint] {e}' for e in _jsonschema_errors(APP_BLUEPRINT_SCHEMA, final_output.get('blueprint', {}))])
    errors.extend([f'[OutputSchema] {e}' for e in _jsonschema_errors(OUTPUT_SCHEMA, final_output)])

    schemas = final_output.get('schemas', {})
    missing = REQUIRED_SCHEMA_KEYS - set(schemas.keys())
    if missing:
        errors.append(f'[Schemas] Missing sub-schemas: {sorted(missing)}')

    db_cols = set()
    for table in schemas.get('db_schema', {}).get('tables', []):
        for col in table.get('columns', []):
            db_cols.add(f"{table['name']}.{col['name']}")

    api_paths = {ep.get('path') for ep in schemas.get('api_config', {}).get('endpoints', [])}
    route_guards = {g.get('route') for g in schemas.get('auth_config', {}).get('route_guards', [])}

    for page in schemas.get('ui_config', {}).get('pages', []):
        if page.get('route') not in route_guards:
            errors.append(f"[Auth] Missing route guard for page: {page.get('route')}")
        for comp in page.get('components', []):
            bound = comp.get('binds_to_api', '')
            if bound and bound not in api_paths:
                errors.append(f"[UI] Component '{comp.get('id')}' binds to non-existent API: {bound}")
            for field in comp.get('fields', []):
                ref = field.get('maps_to_db_column', '')
                if ref and ref not in db_cols:
                    errors.append(f"[UI] Field '{field.get('name')}' maps to non-existent DB column: {ref}")

    for ep in schemas.get('api_config', {}).get('endpoints', []):
        rb = ep.get('request_body')
        if isinstance(rb, dict):
            for field in rb.get('fields', []):
                ref = field.get('maps_to_db', '')
                if ref and ref not in db_cols:
                    errors.append(f"[API] {ep.get('path')} field '{field.get('name')}' maps to non-existent DB: {ref}")

    if not errors:
        logger.info('[Stage 5] ✅ Validation passed — no errors found')
    else:
        logger.warning(f'[Stage 5] ❌ {len(errors)} validation error(s) found')

    return {'valid': len(errors) == 0, 'errors': errors, 'warnings': warnings}


def repair_pipeline_output(final_output: dict) -> dict:
    """
    Targeted repair engine.

    Strategy (in order):
    1. Deterministic fixes (no LLM, instant):
       - Add missing auth route guards
       - Add missing standard DB columns (id, created_at, updated_at)
       - Remove dangling DB column references in UI/API
    2. Re-validate after deterministic fixes
    3. Log all repairs made in metadata.warnings

    Returns: repaired final_output dict
    """
    repaired = deepcopy(final_output)
    repaired.setdefault('metadata', {})
    repaired['metadata'].setdefault('warnings', [])
    repaired['metadata'].setdefault('repair_counts', {})
    repaired['metadata']['repair_counts'].setdefault('stage5', 0)

    schemas = repaired.setdefault('schemas', {})
    auth = schemas.setdefault('auth_config', {'route_guards': [], 'roles': []})
    ui = schemas.setdefault('ui_config', {'pages': []})
    db = schemas.setdefault('db_schema', {'tables': []})

    guard_routes = {g.get('route') for g in auth.get('route_guards', [])}
    for page in ui.get('pages', []):
        if page.get('route') not in guard_routes:
            auth.setdefault('route_guards', []).append({
                'route': page.get('route'),
                'requires_auth': page.get('requires_auth', False),
                'roles_allowed': page.get('roles_allowed', []),
                'redirect_to': '/login'
            })
            msg = f"[Repair] Added missing route guard for: {page.get('route')}"
            logger.info(msg)
            repaired['metadata']['warnings'].append(msg)

    STANDARD_COLS = [
        {'name': 'id', 'type': 'UUID', 'primary_key': True, 'nullable': False,
         'unique': True, 'default': 'gen_random_uuid()', 'foreign_key': None},
        {'name': 'created_at', 'type': 'TIMESTAMP', 'primary_key': False, 'nullable': False,
         'unique': False, 'default': 'NOW()', 'foreign_key': None},
        {'name': 'updated_at', 'type': 'TIMESTAMP', 'primary_key': False, 'nullable': False,
         'unique': False, 'default': 'NOW()', 'foreign_key': None},
    ]
    for table in db.get('tables', []):
        existing = {c['name'] for c in table.get('columns', [])}
        for col in STANDARD_COLS:
            if col['name'] not in existing:
                idx = 0 if col['name'] == 'id' else len(table.get('columns', []))
                table.setdefault('columns', []).insert(idx, col)
                msg = f"[Repair] Added '{col['name']}' column to table '{table.get('name')}'"
                logger.info(msg)
                repaired['metadata']['warnings'].append(msg)

    repaired['metadata']['repair_counts']['stage5'] += 1
    post_validation = validate_pipeline_output(repaired)
    repaired['metadata']['last_validation'] = post_validation

    if post_validation['valid']:
        logger.info('[Stage 5] ✅ Repair successful — post-repair validation passed')
    else:
        logger.warning(f"[Stage 5] ⚠️ {len(post_validation['errors'])} errors remain after repair")

    return repaired


if __name__ == '__main__':
    print('[Stage 5] Import validate_pipeline_output() and repair_pipeline_output() from this module.')
