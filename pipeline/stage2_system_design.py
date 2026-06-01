"""
Stage 2 -- System Design
Model: qwen/qwen3-32b  (strong structured architecture reasoning)
Exports: design_system(intent) -> dict
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 2 of an AI compiler pipeline. Convert structured intent into full app architecture.

Return ONLY valid JSON:
{
  "app_name": "<name>",
  "architecture_type": "<monolith|microservice|serverless>",
  "pages": [
    { "name": "<page>", "route": "/<path>", "auth_required": true, "roles": ["<role>"], "components": ["<component>"] }
  ],
  "entities": [
    {
      "name": "<Entity>",
      "fields": [ { "name": "<field>", "type": "<string|int|bool|datetime|uuid|text|float>", "required": true, "unique": false } ],
      "relations": [ { "type": "has_many", "target": "<Entity>" } ]
    }
  ],
  "roles": [
    { "name": "<role>", "permissions": ["<resource:action>"] }
  ],
  "flows": [
    { "name": "<flow>", "steps": ["<step1>", "<step2>"] }
  ],
  "business_rules": ["<rule>"]
}
Rules:
- Every page must have a route
- Every entity must have id (uuid) and created_at (datetime)
- No prose, no markdown."""


def design_system(intent: dict) -> dict:
    """Stage 2 entry point -- called by api/app.py"""
    logger.info('[Stage 2] System design via Qwen3 32B')
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='Stage 1 Intent: ' + str(intent),
        temperature=0.1,
        stage_id=2
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        result.pop(k, None)
    # Ensure app_name flows through
    if 'app_name' not in result:
        result['app_name'] = intent.get('app_name', 'Generated App')
    return result


run = design_system
