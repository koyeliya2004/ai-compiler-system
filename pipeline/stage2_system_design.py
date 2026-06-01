"""
Stage 2: System Design Layer
==============================
Converts IntentSchema → AppBlueprint.

Defines: app architecture, entities, flows, roles, page structure, API groups.

Input:  validated IntentSchema dict
Output: validated AppBlueprint dict
"""

import os
import json
import logging
from pathlib import Path

import jsonschema
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.getenv('PIPELINE_LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
with open(ROOT / 'schemas' / 'app_blueprint_schema.json') as f:
    APP_BLUEPRINT_SCHEMA = json.load(f)

SYSTEM_PROMPT = """You are Stage 2 of an AI Compiler pipeline.
You receive a structured IntentSchema and produce an AppBlueprint.

Return ONLY valid JSON — no explanation, no markdown:
{
  "app_name": "string",
  "architecture": "monolith|microservices|serverless",
  "tech_stack": {
    "frontend": "React",
    "backend": "FastAPI",
    "database": "PostgreSQL",
    "auth": "JWT",
    "payments": "Stripe or null"
  },
  "pages": [
    {
      "name": "Dashboard",
      "route": "/dashboard",
      "requires_auth": true,
      "roles_allowed": ["admin", "user"],
      "components": ["StatsCard", "RecentActivity"],
      "api_dependencies": ["/api/stats", "/api/activity"]
    }
  ],
  "api_groups": [
    {
      "name": "Auth",
      "prefix": "/api/auth",
      "endpoints": ["POST /login", "POST /register", "POST /logout"]
    }
  ],
  "db_entities": [
    {
      "name": "User",
      "fields": ["id", "email", "password_hash", "role", "created_at"],
      "indexes": ["email"],
      "relations": []
    }
  ],
  "auth_strategy": {
    "type": "JWT",
    "roles": ["admin", "user"],
    "session_duration_hours": 24
  },
  "business_rules": [
    "Only admins can access /admin routes",
    "Premium users can access payment features"
  ]
}

Rules:
- Every page must have at least one api_dependency
- Every role in intent must appear in auth_strategy.roles
- business_rules must reflect all role/premium constraints from intent
"""


def validate_blueprint_schema(data: dict) -> list:
    """Validate against AppBlueprintSchema. Returns list of error strings."""
    return [str(e.message) for e in jsonschema.Draft7Validator(APP_BLUEPRINT_SCHEMA).iter_errors(data)]


def design_system(intent: dict, max_retries: int = 2) -> dict:
    """
    Stage 2: Convert IntentSchema to AppBlueprint.
    """
    from llm_client import chat_completion_json

    intent_str = json.dumps(intent, indent=2)

    for attempt in range(max_retries + 1):
        try:
            logger.info(f'[Stage 2] Designing system (attempt {attempt + 1})')
            result = chat_completion_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=f'IntentSchema:\n{intent_str}',
                temperature=0.1 if attempt == 0 else 0.05
            )

            errors = validate_blueprint_schema(result)
            if not errors:
                logger.info('[Stage 2] ✅ Blueprint validated')
                return result

            logger.warning(f'[Stage 2] Validation failed (attempt {attempt + 1}): {errors}')
            if attempt < max_retries:
                intent_str = f'{intent_str}\n\nPrevious attempt errors: {errors}. Fix and return valid JSON.'

        except Exception as e:
            logger.error(f'[Stage 2] Error on attempt {attempt + 1}: {e}')
            if attempt == max_retries:
                raise

    raise ValueError('[Stage 2] Failed to generate valid blueprint after max retries')


if __name__ == '__main__':
    from stage1_intent_extraction import extract_intent
    intent = extract_intent('Build a CRM with login, contacts, dashboard, and admin analytics.')
    print(json.dumps(design_system(intent), indent=2))
