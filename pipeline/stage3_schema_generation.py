"""
Stage 3 — Schema Generation
Converts AppBlueprint → UI config + API config + DB schema + Auth config.
"""
import os
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a full-stack architect. Given an AppBlueprint JSON, generate a complete schemas JSON.

Output ONLY valid JSON with EXACTLY these top-level keys:
{
  "ui_config": {
    "pages": [
      {
        "id": string,
        "name": string,
        "route": string,
        "auth_required": boolean,
        "allowed_roles": [string],
        "components": [{"type": string, "props": {}}]
      }
    ],
    "theme": {"primary_color": string, "layout": string}
  },
  "api_config": {
    "base_path": "/api/v1",
    "endpoints": [
      {
        "id": string,
        "method": "GET"|"POST"|"PUT"|"DELETE"|"PATCH",
        "path": string,
        "auth_required": boolean,
        "allowed_roles": [string],
        "request_body": {} | null,
        "response_schema": {}
      }
    ]
  },
  "db_schema": {
    "database_type": "postgresql"|"mysql"|"sqlite",
    "tables": [
      {
        "name": string,
        "columns": [{"name": string, "type": string, "nullable": boolean, "primary_key": boolean}],
        "relations": [{"type": "has_many"|"belongs_to"|"many_to_many", "target_table": string}]
      }
    ]
  },
  "auth_config": {
    "strategy": "jwt"|"session"|"oauth2",
    "roles": [string],
    "permissions": {"role_name": ["entity:action"]},
    "token_expiry_hours": number
  }
}

Rules:
- Every API endpoint that writes data must have request_body defined
- Every table must have an 'id' column as primary key
- API paths must match UI routes logically
- All roles in auth_config.roles must appear in at least one endpoint's allowed_roles
- Output must be valid JSON with no trailing commas or comments
"""


def generate_schemas(blueprint: dict) -> dict:
    """Stage 3: Blueprint → UI + API + DB + Auth schemas."""
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.1,
                max_tokens=4096,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Blueprint:\n{json.dumps(blueprint, indent=2)}"}
                ]
            )
            raw = resp.choices[0].message.content
            schemas = json.loads(raw)
            logger.info(
                f"[Stage3] pages={len(schemas.get('ui_config',{}).get('pages',[]))} "
                f"endpoints={len(schemas.get('api_config',{}).get('endpoints',[]))} "
                f"tables={len(schemas.get('db_schema',{}).get('tables',[]))}"
            )
            return schemas
        except Exception as e:
            logger.warning(f"[Stage3] Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                raise RuntimeError(f"Stage 3 failed after 3 attempts: {e}")
