"""
Stage 2 -- System Design
Model: llama-3.3-70b-versatile
Exports: design_system(intent) -> dict, run = design_system
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 2 of an AI compiler. Convert app intent into a system design.
Return ONLY a JSON object with these fields:
{
  "app_name": "string",
  "app_type": "string",
  "entities": [
    {"name": "string", "fields": ["string"], "relations": ["string"]}
  ],
  "pages": [
    {"name": "string", "path": "string", "access": "public|authenticated|admin"}
  ],
  "api_groups": [
    {"resource": "string", "endpoints": [
      {"method": "GET|POST|PUT|DELETE", "path": "string", "auth_required": true}
    ]}
  ],
  "roles": ["string"],
  "business_rules": ["string"]
}
Rules: Return valid JSON only. No markdown. No explanation."""


def design_system(intent: dict) -> dict:
    import json
    logger.info('[Stage 2] Designing system for: %s', intent.get('app_name', '?'))
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='Intent: ' + json.dumps(intent),
        temperature=0.1,
        stage_id=2
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        result.pop(k, None)
    # Fill missing keys with safe defaults
    defaults = {
        'app_name': intent.get('app_name', 'App'),
        'app_type': intent.get('app_type', 'SaaS'),
        'entities': [], 'pages': [], 'api_groups': [],
        'roles': intent.get('roles', ['user', 'admin']),
        'business_rules': []
    }
    for k, v in defaults.items():
        if k not in result:
            result[k] = v
    return result


run = design_system
