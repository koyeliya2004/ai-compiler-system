"""
Stage 1: Intent Extraction
==========================
Parses a raw natural language prompt into a structured IntentSchema.

This is the FIRST stage of the AI Compiler pipeline.
Output: IntentSchema (validated JSON)
"""

import os
import json
import logging
from typing import Optional
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv
import jsonschema

load_dotenv()

logging.basicConfig(level=os.getenv("PIPELINE_LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_REPAIR_ATTEMPTS = int(os.getenv("MAX_REPAIR_ATTEMPTS", 3))

# Load the IntentSchema contract
SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "intent_schema.json"
with open(SCHEMA_PATH) as f:
    INTENT_SCHEMA = json.load(f)


SYSTEM_PROMPT = """
You are Stage 1 of an AI Compiler pipeline: Intent Extraction.

Your job is to parse a user's natural language app description into a strict JSON object 
conforming to the IntentSchema contract.

Rules:
1. Output ONLY valid JSON — no markdown, no explanation, no code blocks.
2. ALL required fields must be present: app_name, app_type, features, entities, roles, auth_required, assumptions.
3. Infer missing details intelligently and document them in 'assumptions'.
4. If the prompt is too vague to continue, still produce a best-effort JSON and populate 'clarifications_needed'.
5. features must have at minimum 1 item. Each feature needs: name, description, priority.
6. entities must reflect the real data models needed (e.g., User, Contact, Order).
7. roles must include at least one role (e.g., 'user', 'admin').
8. payment_required and premium_features are optional — include only if mentioned.

The IntentSchema structure:
{
  "app_name": string,
  "app_type": one of [CRM, E-Commerce, SaaS, Dashboard, Blog, Marketplace, Social, Internal Tool, Other],
  "description": string,
  "features": [{name, description, priority, requires_auth, roles_allowed}],
  "entities": [{name, fields: [{name, type, required, unique}]}],
  "roles": [{name, permissions: [string], is_default}],
  "auth_required": boolean,
  "payment_required": boolean,
  "premium_features": [string],
  "assumptions": [string],
  "clarifications_needed": [string]
}
"""


def extract_intent(user_prompt: str, repair_attempt: int = 0) -> dict:
    """
    Stage 1: Extract structured intent from a natural language prompt.
    
    Args:
        user_prompt: Raw user input describing the app to build
        repair_attempt: Current repair attempt number (for logging)
    
    Returns:
        Validated IntentSchema dict
    
    Raises:
        ValueError: If extraction fails after MAX_REPAIR_ATTEMPTS
    """
    logger.info(f"[Stage 1] Extracting intent (attempt {repair_attempt + 1})")
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Parse this app description into IntentSchema JSON:\n\n{user_prompt}"}
    ]
    
    # If this is a repair attempt, add the previous error context
    if repair_attempt > 0:
        messages.append({
            "role": "user",
            "content": f"Your previous response had validation errors. Please fix and return valid JSON only."
        })
    
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.1,  # Low temp for determinism
        response_format={"type": "json_object"}  # Enforce JSON output
    )
    
    raw_output = response.choices[0].message.content
    logger.debug(f"[Stage 1] Raw LLM output: {raw_output[:200]}...")
    
    # Parse JSON
    try:
        intent_data = json.loads(raw_output)
    except json.JSONDecodeError as e:
        logger.error(f"[Stage 1] JSON parse error: {e}")
        if repair_attempt < MAX_REPAIR_ATTEMPTS:
            return _repair_intent(user_prompt, raw_output, str(e), repair_attempt)
        raise ValueError(f"Stage 1 failed: Invalid JSON after {MAX_REPAIR_ATTEMPTS} attempts")
    
    # Validate against IntentSchema
    validation_errors = validate_intent_schema(intent_data)
    if validation_errors:
        logger.warning(f"[Stage 1] Schema validation errors: {validation_errors}")
        if repair_attempt < MAX_REPAIR_ATTEMPTS:
            return _repair_intent(user_prompt, raw_output, str(validation_errors), repair_attempt)
        raise ValueError(f"Stage 1 failed: Schema validation failed after {MAX_REPAIR_ATTEMPTS} attempts")
    
    logger.info(f"[Stage 1] ✅ Intent extracted successfully: {intent_data['app_name']}")
    return intent_data


def _repair_intent(original_prompt: str, bad_output: str, error: str, attempt: int) -> dict:
    """
    Targeted repair: Re-generate only the failed IntentSchema with error context.
    This is NOT a blind full retry — we feed the exact error back.
    """
    logger.info(f"[Stage 1] 🔧 Repairing intent (attempt {attempt + 1}/{MAX_REPAIR_ATTEMPTS})")
    
    repair_prompt = f"""You previously generated this JSON:
{bad_output}

It failed with this error:
{error}

Fix ONLY the issues described above. Return valid JSON conforming to IntentSchema.
Do not change parts that were already correct.
Original user prompt: {original_prompt}"""
    
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": repair_prompt}
        ],
        temperature=0.05,  # Even lower temp for repairs
        response_format={"type": "json_object"}
    )
    
    repaired_output = response.choices[0].message.content
    
    try:
        repaired_data = json.loads(repaired_output)
    except json.JSONDecodeError as e:
        if attempt + 1 < MAX_REPAIR_ATTEMPTS:
            return _repair_intent(original_prompt, repaired_output, str(e), attempt + 1)
        raise ValueError(f"Stage 1 repair failed: {e}")
    
    errors = validate_intent_schema(repaired_data)
    if errors:
        if attempt + 1 < MAX_REPAIR_ATTEMPTS:
            return _repair_intent(original_prompt, repaired_output, str(errors), attempt + 1)
        raise ValueError(f"Stage 1 repair failed after {attempt + 1} attempts: {errors}")
    
    logger.info(f"[Stage 1] ✅ Repair successful")
    return repaired_data


def validate_intent_schema(data: dict) -> list:
    """
    Validate data against the IntentSchema JSON Schema contract.
    Returns list of error messages (empty if valid).
    """
    validator = jsonschema.Draft7Validator(INTENT_SCHEMA)
    errors = [str(e.message) for e in validator.iter_errors(data)]
    return errors


def handle_vague_prompt(intent_data: dict) -> dict:
    """
    Post-process: if the prompt was vague, log clarifications needed
    and document assumptions made. The system continues (doesn't block).
    """
    if intent_data.get("clarifications_needed"):
        logger.warning("[Stage 1] ⚠️ Vague prompt detected. Clarifications needed:")
        for q in intent_data["clarifications_needed"]:
            logger.warning(f"  - {q}")
    
    if intent_data.get("assumptions"):
        logger.info("[Stage 1] 📝 Assumptions made:")
        for a in intent_data["assumptions"]:
            logger.info(f"  - {a}")
    
    return intent_data


if __name__ == "__main__":
    # Demo: Run Stage 1 on the example CRM prompt from the task spec
    demo_prompt = (
        "Build a CRM with login, contacts, dashboard, role-based access, "
        "and premium plan with payments. Admins can see analytics."
    )
    
    print("=" * 60)
    print("AI COMPILER — Stage 1: Intent Extraction")
    print("=" * 60)
    print(f"Input prompt: {demo_prompt}")
    print()
    
    result = extract_intent(demo_prompt)
    result = handle_vague_prompt(result)
    
    print("\n📋 Extracted Intent:")
    print(json.dumps(result, indent=2))
