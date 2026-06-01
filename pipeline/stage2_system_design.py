"""
Stage 2 — System Design Layer
Converts extracted intent → AppBlueprint.
"""
import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a senior software architect. Given a structured intent JSON, produce a detailed AppBlueprint JSON.
Output ONLY valid JSON with EXACTLY these top-level keys:
{
  "app_name": "string",
  "architecture": "monolith",
  "entities": [{"name": "string", "fields": [{"name": "string", "type": "string", "required": true}], "relations": []}],
  "flows": [{"name": "string", "steps": [], "involved_roles": []}],
  "roles": [{"name": "string", "permissions": []}],
  "integrations": [],
  "tech_stack": {"frontend": "React", "backend": "FastAPI", "database": "PostgreSQL", "auth": "JWT"}
}
Rules:
- Every entity referenced in flows must exist in entities[]
- permissions must be in format "entity:action" e.g. "contact:read"
- Output must be valid JSON with no trailing commas
"""


def design_system(intent: dict) -> dict:
    """Stage 2: Intent → AppBlueprint."""
    from llm_client import chat_completion_json
    for attempt in range(3):
        try:
            result = chat_completion_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=f"Intent:\n{json.dumps(intent, indent=2)}",
                temperature=0.1
            )
            logger.info(f"[Stage2] entities={len(result.get('entities', []))} roles={len(result.get('roles', []))}")
            return result
        except Exception as e:
            logger.warning(f"[Stage2] Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                raise RuntimeError(f"Stage 2 failed: {e}")
