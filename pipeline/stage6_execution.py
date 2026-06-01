"""
Stage 6 -- Execution Readiness
Model: openai/gpt-oss-120b  (most authoritative final pass)
Exports: check_execution_readiness(output) -> dict
"""
import logging
from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Stage 6 of an AI compiler pipeline: the Execution Readiness checker.

Assess whether the output can power a real application. Return ONLY valid JSON:
{
  "is_executable": true,
  "issues": [],
  "preview": {
    "boot_log": [
      "DB schema loaded: <N> tables",
      "Auth strategy: <strategy>",
      "API routes registered: <N>",
      "UI pages mapped: <N>",
      "Role guards active: <roles>"
    ]
  }
}
If critical issues exist, set is_executable=false and list them in issues[].
No prose, no markdown."""


def check_execution_readiness(output: dict) -> dict:
    """Stage 6 entry point -- called by api/app.py"""
    logger.info('[Stage 6] Execution check via GPT-OSS 120B')
    schemas = output.get('schemas', {})
    # Use repaired_schemas if available from stage 5
    if isinstance(schemas, dict) and 'repaired_schemas' in schemas:
        schemas = schemas['repaired_schemas']

    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt='Validated schemas: ' + str(schemas),
        temperature=0.05,
        stage_id=6
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        result.pop(k, None)
    return result


run = check_execution_readiness
