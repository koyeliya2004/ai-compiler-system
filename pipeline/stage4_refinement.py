"""
Stage 4 -- Refinement & Cross-Layer Consistency
Model: openai/gpt-oss-20b  (fast + smart for consistency fixes)
Exports: refine_schemas(schemas) -> dict
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 4 of an AI compiler pipeline. Cross-validate and fix inconsistencies across schema layers.

Check and fix:
1. API fields not in DB schema -> add missing DB columns
2. UI components referencing missing API routes -> add endpoints
3. Auth route_guards missing UI routes -> add them
4. DB foreign keys to non-existent tables -> fix
5. Role name mismatches across layers -> normalize

Return the COMPLETE corrected schemas:
{
  "ui_config": { ... },
  "api_config": { ... },
  "db_schema": { ... },
  "auth_config": { ... },
  "refinement_log": ["<description of each fix made>"]
}
If already consistent, return unchanged with empty refinement_log.
No prose, no markdown."""


def refine_schemas(schemas: dict) -> dict:
    """Stage 4 entry point -- called by api/app.py"""
    logger.info('[Stage 4] Refinement via GPT-OSS 20B')
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='Stage 3 Schemas: ' + str(schemas),
        temperature=0.05,
        stage_id=4
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        result.pop(k, None)
    return result


run = refine_schemas
