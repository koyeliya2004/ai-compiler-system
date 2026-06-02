"""
Stage 3 -- Schema Generation
Model: llama-3.3-70b-versatile
Exports: generate_schemas(blueprint) -> dict, run = generate_schemas
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 3 of an AI compiler. Generate 4 implementation schemas from a system design.
Return ONLY a JSON object with these exact top-level keys:
{
  "ui_config": {
    "framework": "react",
    "pages": [
      {"name": "string", "path": "string", "components": ["string"], "auth_required": true}
    ]
  },
  "api_config": {
    "base_path": "/api/v1",
    "auth_type": "jwt",
    "endpoints": [
      {"method": "GET|POST|PUT|DELETE", "path": "string", "description": "string", "auth_required": true}
    ]
  },
  "db_schema": {
    "dialect": "postgresql",
    "tables": [
      {
        "name": "string",
        "columns": [
          {"name": "string", "type": "string", "nullable": false, "primary_key": false, "unique": false}
        ],
        "foreign_keys": [
          {"column": "string", "references": "table.column"}
        ]
      }
    ]
  },
  "auth_config": {
    "strategy": "jwt",
    "roles": ["string"],
    "token_expiry": "24h",
    "protected_routes": ["string"]
  }
}
Rules: Return valid JSON only. No markdown. No explanation."""


def generate_schemas(blueprint: dict) -> dict:
    import json
    logger.info('[Stage 3] Generating schemas for: %s', blueprint.get('app_name', '?'))
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='System design: ' + json.dumps(blueprint),
        temperature=0.1,
        stage_id=3
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        result.pop(k, None)
    # Fill missing top-level keys with safe defaults
    if 'ui_config' not in result:
        result['ui_config'] = {'framework': 'react', 'pages': []}
    if 'api_config' not in result:
        result['api_config'] = {'base_path': '/api/v1', 'auth_type': 'jwt', 'endpoints': []}
    if 'db_schema' not in result:
        result['db_schema'] = {'dialect': 'postgresql', 'tables': []}
    if 'auth_config' not in result:
        result['auth_config'] = {'strategy': 'jwt', 'roles': ['user', 'admin'], 'token_expiry': '24h', 'protected_routes': []}
    return result


run = generate_schemas
