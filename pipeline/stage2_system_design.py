"""
Stage 2 — System Design Layer
Converts extracted intent → AppBlueprint (entities, flows, roles, architecture).
"""
import os
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a senior software architect. Given a structured intent JSON, produce a detailed AppBlueprint JSON.

Output ONLY valid JSON. No explanation, no markdown, no code blocks.

The output must have EXACTLY these top-level keys:
{
  "app_name": string,
  "architecture": string,         // e.g. "monolith", "microservices"
  "entities": [...],              // list of {name, fields:[{name,type,required}], relations:[]}
  "flows": [...],                 // list of {name, steps:[], involved_roles:[]}
  "roles": [...],                 // list of {name, permissions:[]}
  "integrations": [...],          // e.g. ["stripe", "sendgrid"]
  "tech_stack": {
    "frontend": string,
    "backend": string,
    "database": string,
    "auth": string
  }
}

Rules:
- Every entity referenced in flows/roles must exist in entities[]
- permissions must be in format "entity:action" e.g. "contact:read"
- Output must be parseable JSON with no trailing commas
"""


def design_system(intent: dict) -> dict:
    """Stage 2: Intent → AppBlueprint."""
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Intent:\n{json.dumps(intent, indent=2)}"}
                ]
            )
            raw = resp.choices[0].message.content
            blueprint = json.loads(raw)
            logger.info(f"[Stage2] Blueprint: {blueprint.get('app_name')} | entities={len(blueprint.get('entities',[]))}")
            return blueprint
        except Exception as e:
            logger.warning(f"[Stage2] Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                raise RuntimeError(f"Stage 2 failed after 3 attempts: {e}")
