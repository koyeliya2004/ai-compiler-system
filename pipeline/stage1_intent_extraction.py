"""
Stage 1 — Intent Extraction
Model: openai/gpt-oss-120b (best NL understanding)
"""
import json
import logging
from jsonschema import validate, ValidationError
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

INTENT_SCHEMA = {
    "type": "object",
    "required": ["app_name","app_type","description","features","roles","entities","integrations","assumptions","clarifications_needed"],
    "properties": {
        "app_name":             {"type": "string"},
        "app_type":             {"type": "string"},
        "description":          {"type": "string"},
        "features":             {"type": "array",  "items": {"type": "object"}},
        "roles":                {"type": "array",  "items": {"type": "string"}},
        "entities":             {"type": "array",  "items": {"type": "string"}},
        "integrations":         {"type": "array",  "items": {"type": "string"}},
        "assumptions":          {"type": "array",  "items": {"type": "string"}},
        "clarifications_needed":{"type": "array",  "items": {"type": "string"}}
    }
}

SYSTEM_PROMPT = """You are Stage 1 of an AI compiler pipeline. Your job: extract structured intent from a natural language app description.

Return ONLY valid JSON with these exact fields:
{
  "app_name": "<short name>",
  "app_type": "<CRM|E-commerce|Social|SaaS|Analytics|ProjectMgmt|Other>",
  "description": "<one sentence>",
  "features": [
    {
      "name": "<feature name>",
      "description": "<what it does>",
      "priority": "<must-have|nice-to-have>",
      "requires_auth": true,
      "roles_allowed": ["<role>"]
    }
  ],
  "roles": ["<role1>", "<role2>"],
  "entities": ["<entity1>", "<entity2>"],
  "integrations": ["<service>"],
  "assumptions": ["<assumption made for vague parts>"],
  "clarifications_needed": ["<question if prompt is ambiguous>"]
}

Rules:
- If prompt is vague, make reasonable assumptions and document them in `assumptions`
- If something is truly unclear, add it to `clarifications_needed`
- Always return valid JSON. No prose, no markdown, no explanation."""


def run(prompt: str) -> dict:
    logger.info('[Stage 1] Starting intent extraction')
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"App description: {prompt}",
        temperature=0.1,
        stage_id=1          # → routes to openai/gpt-oss-120b
    )
    _strip_meta(result)
    _validate_and_repair(prompt, result)
    return result


def _strip_meta(d: dict):
    for k in ['__model_used__','__model_label__','__stage_ms__']:
        d.pop(k, None)


def _validate_and_repair(prompt: str, result: dict, attempt: int = 0):
    try:
        validate(instance=result, schema=INTENT_SCHEMA)
    except ValidationError as e:
        if attempt >= 2:
            raise RuntimeError(f'Stage 1 validation failed after repair: {e.message}')
        logger.warning(f'[Stage 1] Schema validation error: {e.message}. Repairing...')
        repair_prompt = (
            f"The following JSON failed validation: {json.dumps(result)}\n"
            f"Error: {e.message}\n"
            f"Fix ONLY the invalid fields and return the complete corrected JSON."
        )
        repaired = chat_completion_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=repair_prompt,
            temperature=0.05,
            stage_id=1
        )
        _strip_meta(repaired)
        result.clear()
        result.update(repaired)
        _validate_and_repair(prompt, result, attempt + 1)
