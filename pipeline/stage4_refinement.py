"""
Stage 4 — Refinement & Cross-Layer Consistency
Model: openai/gpt-oss-20b (fast + smart for consistency checks)
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 4 of an AI compiler pipeline. Your job: cross-validate and fix inconsistencies across all schema layers.

You will receive the Stage 3 schemas (ui_config, api_config, db_schema, auth_config).
Check and fix:
1. API fields not present in DB schema → add missing DB columns
2. UI components referencing API routes that don't exist → add missing endpoints
3. Auth route_guards missing routes defined in ui_config → add them
4. DB foreign keys referencing non-existent tables → fix references
5. Role mismatches across layers → normalize role names

Return the COMPLETE corrected schemas in the EXACT same structure:
{
  "ui_config": { ... },
  "api_config": { ... },
  "db_schema": { ... },
  "auth_config": { ... },
  "refinement_log": ["<description of each fix made>"]
}

If everything is already consistent, return it unchanged with an empty refinement_log.
No prose, no markdown."""


def run(schemas: dict) -> dict:
    logger.info('[Stage 4] Starting refinement')
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Stage 3 Schemas: {schemas}",
        temperature=0.05,
        stage_id=4          # → routes to openai/gpt-oss-20b
    )
    result.pop('__model_used__', None)
    result.pop('__model_label__', None)
    result.pop('__stage_ms__', None)
    return result
