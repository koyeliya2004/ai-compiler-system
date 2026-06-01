"""
Stage 1: Intent Extraction
===========================
Parses raw user prompt into a strict, validated IntentSchema.
Includes failure handling for vague, conflicting, underspecified prompts.

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

SYSTEM_PROMPT = """You are Stage 1 of an AI Compiler pipeline.
Your job: extract structured intent from a natural language app description.

Return ONLY valid JSON matching this exact schema - no explanation, no markdown:
{
  "app_name": "string",
  "app_type": "CRM|ECommerce|ProjectManagement|Analytics|Social|Marketplace|Other",
  "description": "string",
  "features": [
    {
      "id": "feat_001",
      "name": "string",
      "description": "string",
      "priority": "must_have|should_have|nice_to_have",
      "requires_auth": true,
      "requires_premium": false
    }
  ],
  "entities": [
    {
      "name": "User",
      "attributes": ["id", "email", "name"],
      "relations": []
    }
  ],
  "roles": [
    {"name": "admin", "description": "Full access", "permissions": ["read", "write", "delete"]},
    {"name": "user", "description": "Standard access", "permissions": ["read", "write"]}
  ],
  "auth_required": true,
  "has_payments": false,
  "has_analytics": false,
  "has_premium_tier": false,
  "clarifications_needed": [],
  "assumptions": []
}

Rules:
- features must have at least 1 item
- entities must have at least 1 item  
- roles must have at least 1 item
- If information is vague, make reasonable assumptions and list them in 'assumptions'
- If critical info is missing, list questions in 'clarifications_needed'
"""


def validate_intent_schema(data: dict) -> list:
    """Validate against IntentSchema. Returns list of error strings."""
    return [str(e.message) for e in jsonschema.Draft7Validator(INTENT_SCHEMA).iter_errors(data)]


def extract_intent(prompt: str, max_retries: int = 2) -> dict:
    """
    Stage 1: Extract structured intent from raw prompt.
    Includes failure handling for vague/conflicting/underspecified prompts.
    """
    from llm_client import chat_completion_json
    from pipeline.failure_handler import classify_prompt, enrich_prompt

    # Pre-process: classify and handle problematic prompts
    classification, issues, assumptions = classify_prompt(prompt)
    if issues:
        logger.warning(f'[Stage 1] Prompt classified as {classification}: {issues}')
    enriched_prompt = enrich_prompt(prompt, assumptions)

    for attempt in range(max_retries + 1):
        try:
            logger.info(f'[Stage 1] Extracting intent (attempt {attempt + 1}, type={classification})')
            result = chat_completion_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=f'App description: {enriched_prompt}',
                temperature=0.1 if attempt == 0 else 0.05
            )

            # Inject pre-detected assumptions
            if assumptions:
                result.setdefault('assumptions', [])
                for a in assumptions:
                    if a not in result['assumptions']:
                        result['assumptions'].append(a)

            if issues:
                result.setdefault('clarifications_needed', [])
                for issue in issues:
                    if issue not in result['clarifications_needed']:
                        result['clarifications_needed'].append(issue)

            errors = validate_intent_schema(result)
            if not errors:
                logger.info(f'[Stage 1] Validated. Classification={classification}, Assumptions={len(assumptions)}')
                return result

            logger.warning(f'[Stage 1] Validation failed (attempt {attempt + 1}): {errors}')
            if attempt < max_retries:
                enriched_prompt = f'{enriched_prompt}\n\nPrevious attempt errors: {errors}. Fix them.'

        except Exception as e:
            logger.error(f'[Stage 1] Error on attempt {attempt + 1}: {e}')
            if attempt == max_retries:
                raise

    raise ValueError('[Stage 1] Failed to extract valid intent after max retries')


if __name__ == '__main__':
    import sys
    test_prompt = sys.argv[1] if len(sys.argv) > 1 else 'Build a CRM with login, contacts, dashboard, and admin analytics.'
    print(json.dumps(extract_intent(test_prompt), indent=2))
