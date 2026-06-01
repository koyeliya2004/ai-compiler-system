"""
Stage 2 — System Design
Model: qwen/qwen3-32b (strong structured architecture reasoning)
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 2 of an AI compiler pipeline. Your job: convert structured intent into a full app architecture.

Given the Stage 1 intent JSON, return ONLY valid JSON with this shape:
{
  "architecture_type": "<monolith|microservice|serverless>",
  "pages": [
    { "name": "<page>", "route": "/<path>", "auth_required": true, "roles": ["<role>"], "components": ["<component>"] }
  ],
  "entities": [
    { "name": "<Entity>", "fields": [ { "name": "<field>", "type": "<string|int|bool|datetime|uuid|text|float>", "required": true, "unique": false } ], "relations": [ { "type": "has_many|belongs_to|many_to_many", "target": "<Entity>" } ] }
  ],
  "roles": [
    { "name": "<role>", "permissions": ["<resource:action>"] }
  ],
  "flows": [
    { "name": "<flow name>", "steps": ["<step1>", "<step2>"] }
  ],
  "business_rules": ["<rule1>", "<rule2>"]
}

Rules:
- Every page must have a route
- Every entity must have at least an `id` field (uuid) and `created_at` (datetime)
- Roles must map to realistic permissions
- No prose, no markdown."""


def run(intent: dict) -> dict:
    logger.info('[Stage 2] Starting system design')
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Stage 1 Intent: {intent}",
        temperature=0.1,
        stage_id=2          # → routes to qwen/qwen3-32b
    )
    result.pop('__model_used__', None)
    result.pop('__model_label__', None)
    result.pop('__stage_ms__', None)
    return result
