"""
Stage 6 — Execution Readiness
Model: openai/gpt-oss-120b (most authoritative final pass)
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 6 of an AI compiler pipeline: the Execution Readiness checker.

Given the validated schemas, assess whether the output can power a real application.
Return ONLY valid JSON:
{
  "is_executable": true,
  "issues": [],
  "preview": {
    "boot_log": [
      "\u2705 DB schema loaded: <N> tables",
      "\u2705 Auth strategy: <strategy>",
      "\u2705 API routes registered: <N>",
      "\u2705 UI pages mapped: <N>",
      "\u2705 Role guards active: <roles>"
    ]
  },
  "artifacts": {
    "openapi_stub": {
      "openapi": "3.0.0",
      "info": { "title": "<app_name>", "version": "1.0.0" },
      "paths": { "<endpoint_path>": { "<method>": { "summary": "<desc>", "security": [] } } }
    },
    "db_migration_preview": "<SQL CREATE TABLE statements as a string>"
  }
}

If any critical issues make the output non-executable, set `is_executable: false` and list issues.
No prose, no markdown."""


def run(validated: dict) -> dict:
    logger.info('[Stage 6] Starting execution readiness check')
    schemas = validated.get('repaired_schemas', validated)
    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=f"Validated schemas: {schemas}",
        temperature=0.05,
        stage_id=6          # → routes to openai/gpt-oss-120b
    )
    result.pop('__model_used__', None)
    result.pop('__model_label__', None)
    result.pop('__stage_ms__', None)
    return result
