"""
Stage 3 — Schema Generation
Blueprint → UI + API + DB + Auth schemas.
"""
import json
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a full-stack architect. Given an AppBlueprint JSON, generate a complete schemas JSON.
Output ONLY valid JSON with EXACTLY these top-level keys:
{
  "ui_config": {
    "pages": [{"id": "string", "name": "string", "route": "string", "auth_required": true, "allowed_roles": [], "components": []}],
    "theme": {"primary_color": "#4F46E5", "layout": "sidebar"}
  },
  "api_config": {
    "base_path": "/api/v1",
    "endpoints": [{"id": "string", "method": "GET", "path": "string", "auth_required": true, "allowed_roles": [], "request_body": null, "response_schema": {}}]
  },
  "db_schema": {
    "database_type": "postgresql",
    "tables": [{"name": "string", "columns": [{"name": "id", "type": "uuid", "nullable": false, "primary_key": true}], "relations": []}]
  },
  "auth_config": {
    "strategy": "jwt",
    "roles": [],
    "permissions": {},
    "token_expiry_hours": 24
  }
}
Rules:
- Every table MUST have an id column with primary_key=true
- method must be one of: GET, POST, PUT, DELETE, PATCH
- All roles used in endpoints must also appear in auth_config.roles
- Output valid JSON, no trailing commas
"""


def generate_schemas(blueprint: dict) -> dict:
    """Stage 3: Blueprint → all schemas."""
    from llm_client import chat_completion_json
    for attempt in range(3):
        try:
            result = chat_completion_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=f"Blueprint:\n{json.dumps(blueprint, indent=2)}",
                temperature=0.1
            )
            logger.info(
                f"[Stage3] pages={len(result.get('ui_config',{}).get('pages',[]))} "
                f"endpoints={len(result.get('api_config',{}).get('endpoints',[]))} "
                f"tables={len(result.get('db_schema',{}).get('tables',[]))}"
            )
            return result
        except Exception as e:
            logger.warning(f"[Stage3] Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                raise RuntimeError(f"Stage 3 failed: {e}")
