"""
Stage 5 -- Validation & Repair
Model: llama-3.1-8b-instant  (ultra-fast rule-based checks)
Exports: validate_pipeline_output(output) -> dict
         repair_pipeline_output(output) -> dict
"""
import json
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

REQUIRED_SCHEMA_KEYS = ['ui_config', 'api_config', 'db_schema', 'auth_config']

SYSTEM_PROMPT = """You are Stage 5 of an AI compiler pipeline: the Validator & Repair engine.

Validate the provided schemas and return ONLY valid JSON:
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "repaired_schemas": { <same 4-schema structure with fixes applied> }
}

Validation rules:
- All required keys present: ui_config, api_config, db_schema, auth_config
- No null values for required fields
- All API endpoints have path, method, auth_required
- All DB columns have name and type
- All UI pages have name and route
- Auth roles list is non-empty

If errors found: repair them and list fixes in errors[].
If no errors: set valid=true, errors=[], copy schemas to repaired_schemas unchanged.
No prose, no markdown."""


def validate_pipeline_output(output: dict) -> dict:
    """Stage 5a -- validate. Called by api/app.py"""
    logger.info('[Stage 5] Validating via Llama 3.1 8B')
    schemas = output.get('schemas', {})
    quick_errors = _quick_check(schemas)

    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='Schemas to validate: ' + json.dumps(schemas) + '  Quick-check errors: ' + str(quick_errors),
        temperature=0.05,
        stage_id=5
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        result.pop(k, None)
    return result


def repair_pipeline_output(output: dict) -> dict:
    """Stage 5b -- repair. Called by api/app.py when validation fails."""
    logger.info('[Stage 5] Repairing schemas')
    schemas = output.get('schemas', {})
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='Repair these schemas: ' + json.dumps(schemas),
        temperature=0.05,
        stage_id=5
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        result.pop(k, None)
    repaired = result.get('repaired_schemas', schemas)
    output['schemas'] = repaired
    return output


# Keep run() for direct calls
def run(schemas):
    return validate_pipeline_output({'schemas': schemas})


def _quick_check(schemas):
    errors = []
    for key in REQUIRED_SCHEMA_KEYS:
        if key not in schemas:
            errors.append('Missing: ' + key)
    return errors
