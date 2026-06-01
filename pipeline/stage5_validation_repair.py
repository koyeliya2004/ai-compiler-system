"""
Stage 5 — Validation & Repair
Model: llama-3.1-8b-instant (ultra-fast, rule-based structural checks)
"""
import json
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

REQUIRED_TOP_KEYS = ['ui_config', 'api_config', 'db_schema', 'auth_config']
REQUIRED_UI   = ['pages']
REQUIRED_API  = ['endpoints', 'base_path', 'auth']
REQUIRED_DB   = ['tables', 'dialect']
REQUIRED_AUTH = ['strategy', 'roles', 'route_guards']

SYSTEM_PROMPT = """You are Stage 5 of an AI compiler pipeline: the Validator & Repair engine.

You receive all 4 schemas. Return ONLY valid JSON:
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "repaired_schemas": { <same 4-schema structure, with fixes applied> }
}

Validation rules:
- All required keys present in each schema layer
- No null values for required fields
- All API endpoints have `path`, `method`, `auth_required`
- All DB columns have `name` and `type`
- All UI pages have `name` and `route`
- Auth roles list is non-empty

If errors found: repair them in `repaired_schemas` and list fixes in `errors`.
If no errors: set `valid: true`, `errors: []`, copy schemas to `repaired_schemas` unchanged.
No prose, no markdown."""


def run(schemas: dict) -> dict:
    logger.info('[Stage 5] Starting validation & repair')

    # Fast structural pre-check (no LLM needed for obvious issues)
    quick_errors = _quick_check(schemas)
    if quick_errors:
        logger.warning(f'[Stage 5] Quick-check found {len(quick_errors)} issues, sending to LLM repair')

    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Schemas to validate: {json.dumps(schemas)}\nQuick-check errors found: {quick_errors}",
        temperature=0.05,
        stage_id=5          # → routes to llama-3.1-8b-instant
    )
    result.pop('__model_used__', None)
    result.pop('__model_label__', None)
    result.pop('__stage_ms__', None)
    return result


def _quick_check(schemas: dict) -> list:
    errors = []
    for key in REQUIRED_TOP_KEYS:
        if key not in schemas:
            errors.append(f'Missing top-level key: {key}')
    if 'ui_config' in schemas:
        for k in REQUIRED_UI:
            if k not in schemas['ui_config']:
                errors.append(f'ui_config missing: {k}')
    if 'api_config' in schemas:
        for k in REQUIRED_API:
            if k not in schemas['api_config']:
                errors.append(f'api_config missing: {k}')
    if 'db_schema' in schemas:
        for k in REQUIRED_DB:
            if k not in schemas['db_schema']:
                errors.append(f'db_schema missing: {k}')
    if 'auth_config' in schemas:
        for k in REQUIRED_AUTH:
            if k not in schemas['auth_config']:
                errors.append(f'auth_config missing: {k}')
    return errors
