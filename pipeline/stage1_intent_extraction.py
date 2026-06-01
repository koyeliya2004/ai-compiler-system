"""
Stage 1 — Intent Extraction
============================
Input:  raw natural language prompt (str)
Output: validated IntentSchema dict

Design:
- System prompt is kept in EXACT sync with schemas/intent_schema.json
- On validation failure: targeted repair (feed exact errors back), NOT blind retry
- Handles vague / conflicting / underspecified prompts via failure_handler
"""
import os
import json
import logging
from pathlib import Path

import jsonschema

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

with open(ROOT / 'schemas' / 'intent_schema.json', encoding='utf-8') as f:
    INTENT_SCHEMA = json.load(f)

# ⚠️  Every enum value here MUST exactly match schemas/intent_schema.json
# app_type: CRM | E-Commerce | SaaS | Dashboard | Blog | Marketplace | Social | Internal Tool | Other
# priority: must-have | should-have | nice-to-have  (HYPHENS, not underscores)
# entities[].fields: array of objects {name, type}  (NOT plain strings)
# field type: string|integer|float|boolean|date|datetime|uuid|text|email|url|json

SYSTEM_PROMPT = """\
You are Stage 1 of an AI Compiler pipeline.
Task: extract structured intent from the app description below.

Return ONLY a valid JSON object. No markdown, no backticks, no explanation.

Required structure (copy this exactly, fill in real values):
{
  "app_name": "Short App Name",
  "app_type": "CRM",
  "description": "One sentence describing the app.",
  "features": [
    {
      "name": "User Login",
      "description": "Authenticate users with email and password.",
      "priority": "must-have",
      "requires_auth": false,
      "roles_allowed": []
    }
  ],
  "entities": [
    {
      "name": "User",
      "fields": [
        {"name": "id",       "type": "uuid",    "required": true,  "unique": true},
        {"name": "email",    "type": "email",   "required": true,  "unique": true},
        {"name": "name",     "type": "string",  "required": true,  "unique": false},
        {"name": "role",     "type": "string",  "required": true,  "unique": false},
        {"name": "created_at","type": "datetime","required": true, "unique": false}
      ]
    }
  ],
  "roles": [
    {"name": "admin", "permissions": ["read", "write", "delete"], "is_default": false},
    {"name": "user",  "permissions": ["read", "write"],           "is_default": true}
  ],
  "auth_required": true,
  "payment_required": false,
  "premium_features": [],
  "assumptions": [],
  "clarifications_needed": []
}

STRICT RULES — any violation causes a hard validation error:
1. app_type must be EXACTLY one of (copy/paste, no changes):
   CRM, E-Commerce, SaaS, Dashboard, Blog, Marketplace, Social, Internal Tool, Other
2. priority must be EXACTLY one of (hyphens, NOT underscores):
   must-have, should-have, nice-to-have
3. entities[].fields must be an ARRAY OF OBJECTS with keys: name, type
   WRONG:  "fields": ["id", "email"]
   CORRECT: "fields": [{"name": "id", "type": "uuid", "required": true, "unique": true}]
4. field type must be one of:
   string, integer, float, boolean, date, datetime, uuid, text, email, url, json
5. features, entities, roles must each have at least 1 item
6. assumptions and clarifications_needed must be arrays (empty [] is fine)
7. If the description is vague, make reasonable assumptions and add them to assumptions[]
"""


def validate_intent(data: dict) -> list[str]:
    """Returns list of validation error strings (empty = valid)."""
    return [
        e.message
        for e in jsonschema.Draft7Validator(INTENT_SCHEMA).iter_errors(data)
    ]


def extract_intent(prompt: str, max_retries: int = 3) -> dict:
    """
    Run Stage 1. Returns validated IntentSchema dict.
    Raises ValueError if all attempts fail.
    """
    from llm_client import chat_completion_json
    from pipeline.failure_handler import classify_prompt, enrich_prompt

    classification, issues, assumptions = classify_prompt(prompt)
    if issues:
        logger.warning(f'[S1] Prompt issues ({classification}): {issues}')

    current_user_msg = f'App description: {enrich_prompt(prompt, assumptions)}'

    for attempt in range(max_retries):
        temp = 0.1 if attempt == 0 else 0.05
        logger.info(f'[S1] Attempt {attempt+1}/{max_retries} temp={temp}')

        try:
            result = chat_completion_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=current_user_msg,
                temperature=temp
            )
        except Exception as e:
            logger.error(f'[S1] LLM error attempt {attempt+1}: {e}')
            if attempt == max_retries - 1:
                raise
            continue

        # Inject pre-detected context
        result.setdefault('assumptions', [])
        result.setdefault('clarifications_needed', [])
        for a in assumptions:
            if a not in result['assumptions']:
                result['assumptions'].append(a)
        for issue in issues:
            if issue not in result['clarifications_needed']:
                result['clarifications_needed'].append(issue)

        errors = validate_intent(result)
        if not errors:
            logger.info(f'[S1] ✅ Valid on attempt {attempt+1}')
            return result

        error_lines = '\n'.join(f'  - {e}' for e in errors)
        logger.warning(f'[S1] Validation failed attempt {attempt+1}:\n{error_lines}')

        if attempt < max_retries - 1:
            # Targeted repair: send exact errors + the broken output back
            current_user_msg = (
                f'App description: {prompt}\n\n'
                f'Your previous JSON had these errors:\n{error_lines}\n\n'
                f'Previous output (fix only the errors above):\n'
                f'{json.dumps(result, indent=2)}\n\n'
                f'Reminders:\n'
                f'- priority must use hyphens: must-have / should-have / nice-to-have\n'
                f'- entities[].fields must be objects: {{"name":"id","type":"uuid","required":true}}\n'
                f'- app_type must be one of: CRM, E-Commerce, SaaS, Dashboard, Blog, Marketplace, Social, Internal Tool, Other\n'
                f'Return ONLY the corrected JSON.'
            )

    raise ValueError(
        f'[Stage 1] Could not produce valid IntentSchema after {max_retries} attempts. '
        f'Last errors: {errors}'
    )


if __name__ == '__main__':
    import sys
    test = sys.argv[1] if len(sys.argv) > 1 else \
        'Build a CRM with login, contacts, dashboard, and admin analytics.'
    print(json.dumps(extract_intent(test), indent=2))
