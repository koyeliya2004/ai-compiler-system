"""
Stage 1 -- Intent Extraction
Model: llama-3.3-70b-versatile
Exports: extract_intent(prompt) -> dict, run = extract_intent
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 1 of an AI compiler. Extract structured intent from an app description.
Return ONLY a JSON object with these fields:
{
  "app_name": "string",
  "app_type": "string",
  "description": "string",
  "features": ["string"],
  "roles": ["string"],
  "entities": ["string"],
  "integrations": ["string"],
  "assumptions": ["string"]
}
Rules: Return valid JSON only. No markdown. No explanation."""


def extract_intent(prompt: str) -> dict:
    logger.info('[Stage 1] Extracting intent')
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='App description: ' + prompt,
        temperature=0.1,
        stage_id=1
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        result.pop(k, None)
    # Fill missing keys with safe defaults
    defaults = {
        'app_name': 'App', 'app_type': 'SaaS', 'description': '',
        'features': [], 'roles': ['user', 'admin'],
        'entities': [], 'integrations': [], 'assumptions': []
    }
    for k, v in defaults.items():
        if k not in result:
            result[k] = v
    return result


run = extract_intent
