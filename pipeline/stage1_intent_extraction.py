"""
Stage 1: Intent Extraction
===========================
Parses raw user prompt into a strict, validated IntentSchema.
System prompt is kept in EXACT sync with schemas/intent_schema.json.

Input:  raw natural language string
Output: validated IntentSchema dict
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
with open(ROOT / 'schemas' / 'intent_schema.json') as f:
    INTENT_SCHEMA = json.load(f)

# ⚠️  Every enum value here MUST match schemas/intent_schema.json exactly.
# app_type enum:    "CRM"|"E-Commerce"|"SaaS"|"Dashboard"|"Blog"|"Marketplace"|"Social"|"Internal Tool"|"Other"
# priority enum:    "must-have"|"should-have"|"nice-to-have"   (hyphens, NOT underscores)
# entities.fields:  array of {name, type} objects             (NOT a plain string array)
SYSTEM_PROMPT = """
You are Stage 1 of an AI Compiler pipeline.
Your job: extract structured intent from a natural language app description.

Return ONLY valid JSON — no explanation, no markdown fences, no trailing commas.
The JSON must match this exact structure:

{
  "app_name": "string — short inferred name for the app",
  "app_type": "one of: CRM | E-Commerce | SaaS | Dashboard | Blog | Marketplace | Social | Internal Tool | Other",
  "description": "one-sentence description",
  "features": [
    {
      "name": "string",
      "description": "string",
      "priority": "must-have",
      "requires_auth": true,
      "roles_allowed": ["admin", "user"]
    }
  ],
  "entities": [
    {
      "name": "User",
      "fields": [
        {"name": "id",    "type": "uuid",   "required": true,  "unique": true},
        {"name": "email", "type": "email",  "required": true,  "unique": true},
        {"name": "name",  "type": "string", "required": true,  "unique": false}
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

STRICT RULES — violating any will cause a validation failure:
1. app_type MUST be exactly one of: CRM, E-Commerce, SaaS, Dashboard, Blog, Marketplace, Social, Internal Tool, Other
2. priority MUST be exactly one of: must-have, should-have, nice-to-have   (USE HYPHENS, never underscores)
3. entities[].fields MUST be an array of objects with keys: name (string), type (string)  — NOT a plain string array
4. entity field "type" MUST be one of: string, integer, float, boolean, date, datetime, uuid, text, email, url, json
5. features must have at least 1 item; entities must have at least 1 item; roles must have at least 1 item
6. assumptions and clarifications_needed MUST be arrays (can be empty [])
7. If information is vague, make reasonable assumptions and add them to the 'assumptions' array
"""


def validate_intent_schema(data: dict) -> list:
    """Validate against IntentSchema. Returns list of error message strings."""
    return [str(e.message) for e in jsonschema.Draft7Validator(INTENT_SCHEMA).iter_errors(data)]


def extract_intent(prompt: str, max_retries: int = 3) -> dict:
    """
    Stage 1: Extract structured intent from raw prompt.
    Uses targeted repair on validation failure — never blind full retry.
    """
    from llm_client import chat_completion_json
    from pipeline.failure_handler import classify_prompt, enrich_prompt

    classification, issues, assumptions = classify_prompt(prompt)
    if issues:
        logger.warning(f'[Stage 1] Prompt type={classification}: {issues}')
    user_msg = enrich_prompt(prompt, assumptions)

    for attempt in range(max_retries + 1):
        try:
            temp = 0.1 if attempt == 0 else 0.05
            logger.info(f'[Stage 1] Attempt {attempt + 1}/{max_retries + 1} (temp={temp})')

            result = chat_completion_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=f'App description: {user_msg}',
                temperature=temp
            )

            # Inject pre-detected assumptions
            result.setdefault('assumptions', [])
            result.setdefault('clarifications_needed', [])
            for a in assumptions:
                if a not in result['assumptions']:
                    result['assumptions'].append(a)
            for issue in issues:
                if issue not in result['clarifications_needed']:
                    result['clarifications_needed'].append(issue)

            errors = validate_intent_schema(result)
            if not errors:
                logger.info(f'[Stage 1] ✅ Valid on attempt {attempt + 1}')
                return result

            # Targeted repair — feed exact errors back
            error_list = '\n'.join(f'  - {e}' for e in errors)
            logger.warning(f'[Stage 1] Validation errors (attempt {attempt + 1}):\n{error_list}')

            if attempt < max_retries:
                repair_note = (
                    f'Your previous output had these validation errors. Fix ONLY these issues:\n'
                    f'{error_list}\n\n'
                    f'Reminder:\n'
                    f'- priority must use hyphens: must-have / should-have / nice-to-have\n'
                    f'- entities[].fields must be objects like {{"name":"id","type":"uuid","required":true}}\n'
                    f'- app_type must be one of: CRM, E-Commerce, SaaS, Dashboard, Blog, Marketplace, Social, Internal Tool, Other\n'
                    f'- field type must be one of: string, integer, float, boolean, date, datetime, uuid, text, email, url, json\n'
                    f'Output ONLY the corrected JSON.'
                )
                user_msg = f'App description: {prompt}\n\nPrevious (broken) output:\n{json.dumps(result, indent=2)}\n\n{repair_note}'

        except json.JSONDecodeError as e:
            logger.error(f'[Stage 1] JSON decode error (attempt {attempt + 1}): {e}')
            if attempt < max_retries:
                user_msg = f'App description: {prompt}\n\nERROR: Your last response was not valid JSON. Return ONLY valid JSON, no markdown, no explanation.'
        except Exception as e:
            logger.error(f'[Stage 1] Unexpected error (attempt {attempt + 1}): {e}')
            if attempt == max_retries:
                raise

    raise ValueError(
        f'[Stage 1] Failed to extract valid intent after {max_retries + 1} attempts. '
        f'Check LLM response format and schema contract.'
    )


if __name__ == '__main__':
    import sys
    test = sys.argv[1] if len(sys.argv) > 1 else 'Build a CRM with login, contacts, dashboard, and admin analytics.'
    print(json.dumps(extract_intent(test), indent=2))
