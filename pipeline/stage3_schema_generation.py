"""
Stage 3 — Schema Generation
Model: meta-llama/llama-4-scout-17b-16e-instruct (fast, precise JSON generation)
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 3 of an AI compiler pipeline. Your job: generate four strict schemas from the app architecture.

Return ONLY valid JSON:
{
  "ui_config": {
    "theme": "<light|dark>",
    "pages": [
      { "name": "<page>", "route": "/<path>", "layout": "<sidebar|topnav|blank>", "components": [ { "type": "<Table|Form|Chart|Card|List>", "props": {} } ] }
    ]
  },
  "api_config": {
    "base_path": "/api/v1",
    "auth": "<jwt|session|oauth2>",
    "endpoints": [
      { "path": "/<resource>", "method": "<GET|POST|PUT|DELETE|PATCH>", "auth_required": true, "roles": ["<role>"], "request_body": {}, "response": {} }
    ]
  },
  "db_schema": {
    "dialect": "<postgresql|mysql|sqlite>",
    "tables": [
      { "name": "<table>", "columns": [ { "name": "<col>", "type": "<VARCHAR|INT|BOOLEAN|TIMESTAMP|UUID|TEXT|FLOAT>", "nullable": false, "primary_key": false, "unique": false, "default": null } ], "indexes": ["<col>"], "foreign_keys": [ { "column": "<col>", "references": "<table.col>" } ] }
    ]
  },
  "auth_config": {
    "strategy": "<jwt|session>",
    "token_expiry": "<e.g. 24h>",
    "refresh_token": true,
    "roles": ["<role>"],
    "route_guards": [ { "route": "/<path>", "allowed_roles": ["<role>"] } ]
  }
}

Rules:
- API fields MUST match DB columns
- UI fields MUST map to API endpoints
- No prose, no markdown."""


def run(design: dict) -> dict:
    logger.info('[Stage 3] Starting schema generation')
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Stage 2 Architecture: {design}",
        temperature=0.1,
        stage_id=3          # → routes to meta-llama/llama-4-scout-17b-16e-instruct
    )
    result.pop('__model_used__', None)
    result.pop('__model_label__', None)
    result.pop('__stage_ms__', None)
    return result
