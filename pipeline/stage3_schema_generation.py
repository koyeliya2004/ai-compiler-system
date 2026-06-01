"""
Stage 3: Schema Generation
===========================
Converts AppBlueprint → full schemas: UI, API, DB, Auth.

Input:  validated AppBlueprint dict
Output: dict with keys: ui_config, api_config, db_schema, auth_config
"""

import os
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.getenv('PIPELINE_LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 3 of an AI Compiler pipeline.
You receive an AppBlueprint and produce 4 schemas in one JSON object.

Return ONLY valid JSON with exactly these top-level keys:
{
  "ui_config": {
    "theme": "light",
    "pages": [
      {
        "id": "page_dashboard",
        "name": "Dashboard",
        "route": "/dashboard",
        "requires_auth": true,
        "roles_allowed": ["admin", "user"],
        "layout": "sidebar",
        "components": [
          {
            "id": "comp_stats",
            "type": "StatsCard",
            "binds_to_api": "/api/stats",
            "fields": []
          }
        ]
      }
    ]
  },
  "api_config": {
    "base_url": "/api",
    "auth_header": "Authorization: Bearer <token>",
    "endpoints": [
      {
        "id": "ep_001",
        "path": "/api/auth/login",
        "method": "POST",
        "description": "User login",
        "auth_required": false,
        "roles_allowed": [],
        "request_body": {"fields": [{"name": "email", "type": "string", "required": true, "maps_to_db": "users.email"}, {"name": "password", "type": "string", "required": true, "maps_to_db": null}]},
        "response": {"fields": [{"name": "token", "type": "string"}, {"name": "user", "type": "object"}]}
      }
    ]
  },
  "db_schema": {
    "dialect": "postgresql",
    "tables": [
      {
        "name": "users",
        "columns": [
          {"name": "id", "type": "UUID", "primary_key": true, "nullable": false, "unique": true, "default": "gen_random_uuid()", "foreign_key": null},
          {"name": "email", "type": "VARCHAR(255)", "primary_key": false, "nullable": false, "unique": true, "default": null, "foreign_key": null},
          {"name": "password_hash", "type": "TEXT", "primary_key": false, "nullable": false, "unique": false, "default": null, "foreign_key": null},
          {"name": "role", "type": "VARCHAR(50)", "primary_key": false, "nullable": false, "unique": false, "default": "user", "foreign_key": null},
          {"name": "created_at", "type": "TIMESTAMP", "primary_key": false, "nullable": false, "unique": false, "default": "NOW()", "foreign_key": null},
          {"name": "updated_at", "type": "TIMESTAMP", "primary_key": false, "nullable": false, "unique": false, "default": "NOW()", "foreign_key": null}
        ],
        "indexes": ["email"],
        "relations": []
      }
    ]
  },
  "auth_config": {
    "strategy": "JWT",
    "token_expiry_hours": 24,
    "roles": [
      {"name": "admin", "permissions": ["read", "write", "delete", "manage_users"]},
      {"name": "user", "permissions": ["read", "write"]}
    ],
    "route_guards": [
      {"route": "/dashboard", "requires_auth": true, "roles_allowed": ["admin", "user"], "redirect_to": "/login"},
      {"route": "/login", "requires_auth": false, "roles_allowed": [], "redirect_to": null}
    ],
    "permissions": {
      "admin": ["read", "write", "delete", "manage_users"],
      "user": ["read", "write"]
    }
  }
}

CRITICAL RULES:
- Every page route in ui_config must have a matching route_guard in auth_config
- Every binds_to_api value must match a real path in api_config.endpoints
- Every maps_to_db value must match a real table.column in db_schema (format: table.column)
- Every role in ui_config/api_config must exist in auth_config.roles
"""


def generate_schemas(blueprint: dict, max_retries: int = 2) -> dict:
    """
    Stage 3: Generate UI, API, DB, and Auth schemas from AppBlueprint.
    """
    from llm_client import chat_completion_json

    blueprint_str = json.dumps(blueprint, indent=2)

    for attempt in range(max_retries + 1):
        try:
            logger.info(f'[Stage 3] Generating schemas (attempt {attempt + 1})')
            result = chat_completion_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=f'AppBlueprint:\n{blueprint_str}',
                temperature=0.1 if attempt == 0 else 0.05,
                max_tokens=8192
            )

            required_keys = {'ui_config', 'api_config', 'db_schema', 'auth_config'}
            missing = required_keys - set(result.keys())
            if not missing:
                logger.info('[Stage 3] ✅ All 4 schemas generated')
                return result

            logger.warning(f'[Stage 3] Missing keys (attempt {attempt + 1}): {missing}')
            if attempt < max_retries:
                blueprint_str = f'{blueprint_str}\n\nMissing keys: {missing}. Return all 4 keys.'

        except Exception as e:
            logger.error(f'[Stage 3] Error on attempt {attempt + 1}: {e}')
            if attempt == max_retries:
                raise

    raise ValueError('[Stage 3] Failed to generate valid schemas after max retries')


if __name__ == '__main__':
    from stage1_intent_extraction import extract_intent
    from stage2_system_design import design_system
    intent = extract_intent('Build a CRM with login, contacts, dashboard, and admin analytics.')
    blueprint = design_system(intent)
    print(json.dumps(generate_schemas(blueprint), indent=2))
