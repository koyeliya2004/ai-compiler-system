"""
Stage 5 — Validation + Repair Engine
Core of the system. Validates output against schema contracts.
On failure: targeted repair (not blind retry).
"""
import os
import json
import logging
from pathlib import Path
from groq import Groq

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]

REQUIRED_SCHEMA_KEYS = {
    "ui_config": ["pages"],
    "api_config": ["base_path", "endpoints"],
    "db_schema": ["tables"],
    "auth_config": ["strategy", "roles"],
}


def validate_pipeline_output(output: dict) -> dict:
    """Validate pipeline output. Returns {valid, errors, warnings}."""
    errors = []
    warnings = []
    schemas = output.get("schemas", {})

    # 1. Required top-level schema keys
    for section, keys in REQUIRED_SCHEMA_KEYS.items():
        if section not in schemas:
            errors.append(f"Missing schemas.{section}")
            continue
        for key in keys:
            if key not in schemas[section]:
                errors.append(f"schemas.{section} missing required key: '{key}'")

    # 2. Cross-layer: API roles must exist in auth_config
    auth_roles = set(schemas.get("auth_config", {}).get("roles", []))
    for ep in schemas.get("api_config", {}).get("endpoints", []):
        for role in ep.get("allowed_roles", []):
            if role and role not in auth_roles:
                errors.append(f"API endpoint '{ep.get('path','')}' uses role '{role}' not in auth_config.roles")

    # 3. UI pages: auth roles must exist
    for page in schemas.get("ui_config", {}).get("pages", []):
        for role in page.get("allowed_roles", []):
            if role and role not in auth_roles:
                warnings.append(f"UI page '{page.get('route','')}' references unknown role '{role}'")

    # 4. DB tables must have id column
    for table in schemas.get("db_schema", {}).get("tables", []):
        col_names = [c.get("name") for c in table.get("columns", [])]
        if "id" not in col_names:
            errors.append(f"DB table '{table.get('name','')}' missing 'id' primary key column")

    # 5. Every endpoint should have a path
    for i, ep in enumerate(schemas.get("api_config", {}).get("endpoints", [])):
        if not ep.get("path"):
            errors.append(f"API endpoint[{i}] missing 'path'")
        if not ep.get("method"):
            errors.append(f"API endpoint[{i}] missing 'method'")

    valid = len(errors) == 0
    logger.info(f"[Stage5] Validation: valid={valid} errors={len(errors)} warnings={len(warnings)}")
    return {"valid": valid, "errors": errors, "warnings": warnings}


def repair_pipeline_output(output: dict) -> dict:
    """Targeted repair: fix only the broken sections, not a full regeneration."""
    validation = validate_pipeline_output(output)
    if validation["valid"]:
        return output

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    error_summary = "\n".join(f"- {e}" for e in validation["errors"])
    repair_prompt = f"""
The following schemas JSON has validation errors. Fix ONLY the specific errors listed.
Do NOT change anything that is already correct.
Return the complete fixed schemas JSON.

Errors to fix:
{error_summary}

Schemas:
{json.dumps(output.get('schemas', {}), indent=2)}

Output ONLY valid JSON with keys: ui_config, api_config, db_schema, auth_config
"""
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.05,
                max_tokens=4096,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": repair_prompt}]
            )
            repaired = json.loads(resp.choices[0].message.content)
            output["schemas"] = repaired
            logger.info(f"[Stage5] Repair attempt {attempt+1} complete")
            return output
        except Exception as e:
            logger.warning(f"[Stage5] Repair attempt {attempt+1} failed: {e}")

    logger.warning("[Stage5] All repair attempts failed, returning as-is")
    return output
