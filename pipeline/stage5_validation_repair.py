"""
Stage 5 — Validation + Repair Engine
"""
import json
import logging

logger = logging.getLogger(__name__)

REQUIRED_SCHEMA_KEYS = {
    'ui_config': ['pages'],
    'api_config': ['base_path', 'endpoints'],
    'db_schema': ['tables'],
    'auth_config': ['strategy', 'roles'],
}


def validate_pipeline_output(output: dict) -> dict:
    errors, warnings = [], []
    schemas = output.get('schemas', {})

    for section, keys in REQUIRED_SCHEMA_KEYS.items():
        if section not in schemas:
            errors.append(f'Missing schemas.{section}')
            continue
        for key in keys:
            if key not in schemas[section]:
                errors.append(f'schemas.{section} missing key: {key!r}')

    auth_roles = set(schemas.get('auth_config', {}).get('roles', []))
    for ep in schemas.get('api_config', {}).get('endpoints', []):
        for role in ep.get('allowed_roles', []):
            if role and role not in auth_roles:
                errors.append(f"Endpoint '{ep.get('path','')}' uses unknown role '{role}'")

    for table in schemas.get('db_schema', {}).get('tables', []):
        col_names = [c.get('name') for c in table.get('columns', [])]
        if 'id' not in col_names:
            errors.append(f"Table '{table.get('name','')}' missing 'id' primary key")

    valid = len(errors) == 0
    logger.info(f'[Stage5] valid={valid} errors={len(errors)} warnings={len(warnings)}')
    return {'valid': valid, 'errors': errors, 'warnings': warnings}


def repair_pipeline_output(output: dict) -> dict:
    validation = validate_pipeline_output(output)
    if validation['valid']:
        return output

    from llm_client import chat_completion_json
    error_summary = '\n'.join(f'- {e}' for e in validation['errors'])
    prompt = f"""Fix these validation errors in the schemas JSON.
Return ONLY the fixed JSON with keys: ui_config, api_config, db_schema, auth_config.

Errors:\n{error_summary}\n\nSchemas:\n{json.dumps(output.get('schemas', {}), indent=2)}"""

    for attempt in range(3):
        try:
            repaired = chat_completion_json(
                system_prompt='You are a JSON schema repair engine. Fix only the listed errors.',
                user_prompt=prompt,
                temperature=0.05
            )
            output['schemas'] = repaired
            logger.info(f'[Stage5] Repaired on attempt {attempt+1}')
            return output
        except Exception as e:
            logger.warning(f'[Stage5] Repair attempt {attempt+1} failed: {e}')

    return output
