"""
Stage 1 -- Intent Extraction
Model: openai/gpt-oss-120b  (best NL understanding)
Exports: extract_intent(prompt) -> dict
"""
import json
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 1 of an AI compiler pipeline. Extract structured intent from a natural language app description.

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
  "clarifications_needed": ["<question if truly ambiguous>"]
}
Rules:
- If vague, make reasonable assumptions and document them in `assumptions`
- Always return valid JSON. No prose, no markdown, no explanation."""


def extract_intent(prompt: str) -> dict:
    """Stage 1 entry point -- called by api/app.py"""
    logger.info('[Stage 1] Intent extraction via GPT-OSS 120B')
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='App description: ' + prompt,
        temperature=0.1,
        stage_id=1
    )
    _strip_meta(result)
    _repair_if_needed(prompt, result)
    return result


# Keep run() as alias so direct calls still work
run = extract_intent


def _strip_meta(d):
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        d.pop(k, None)


def _repair_if_needed(prompt, result, attempt=0):
    required = ['app_name', 'app_type', 'description', 'features', 'roles',
                'entities', 'integrations', 'assumptions', 'clarifications_needed']
    missing = [k for k in required if k not in result]
    if not missing:
        return
    if attempt >= 2:
        # Fill missing keys with safe defaults rather than crash
        for k in missing:
            if k in ('features', 'roles', 'entities', 'integrations',
                     'assumptions', 'clarifications_needed'):
                result[k] = []
            else:
                result[k] = ''
        return
    logger.warning('[Stage 1] Missing keys %s, repairing...', missing)
    repair_prompt = (
        'The following JSON is missing required keys ' + str(missing) + '.\n'
        'Original JSON: ' + json.dumps(result) + '\n'
        'Fix ONLY the missing fields and return the complete corrected JSON.'
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
    _repair_if_needed(prompt, result, attempt + 1)
