"""
Stage 3 -- Schema Generation
Model: meta-llama/llama-4-scout-17b-16e-instruct  (fast + precise JSON)
Exports: generate_schemas(blueprint) -> dict
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 3 of an AI compiler pipeline. Generate four strict schemas from app architecture.

Return ONLY valid JSON:
{
  "ui_config": {
    "theme": "light",
    "pages": [
      { "name": "<page>", "route": "/<path>", "layout": "<sidebar|topnav|blank>",
        "components": [ { "type": "<Table|Form|Chart|Card|List>", "props": {} } ] }
    ]
  },
  "api_config": {
    "base_path": "/api/v1",
    "auth": "jwt",
    "endpoints": [
      { "path": "/<resource>", "method": "<GET|POST|PUT|DELETE|PATCH>",
        "auth_required": true, "roles": ["<role>"], "request_body": {}, "response": {} }
    ]
  },
  "db_schema": {
    "dialect": "postgresql",
    "tables": [
      { "name": "<table>",
        "columns": [ { "name": "<col>", "type": "<VARCHAR|INT|BOOLEAN|TIMESTAMP|UUID|TEXT|FLOAT>",
                       "nullable": false, "primary_key": false, "unique": false, "default": null } ],
        "indexes": [],
        "foreign_keys": [ { "column": "<col>", "references": "<table.col>" } ] }
    ]
  },
  "auth_config": {
    "strategy": "jwt",
    "token_expiry": "24h",
    "refresh_token": true,
    "roles": ["<role>"],
    "route_guards": [ { "route": "/<path>", "allowed_roles": ["<role>"] } ]
  }
}
Rules:
- API fields MUST match DB columns
- UI fields MUST map to API endpoints
- No prose, no markdown."""


def generate_schemas(blueprint: dict) -> dict:
    """Stage 3 entry point -- called by api/app.py"""
    logger.info('[Stage 3] Schema generation via Llama-4 Scout')
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='Stage 2 Architecture: ' + str(blueprint),
        temperature=0.1,
        stage_id=3
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        result.pop(k, None)
    return result


run = generate_schemas
