"""
LLM Client — Groq Only
========================
Single responsibility: call Groq, return a parsed dict.
Handles:
  - Missing API key → clear error message
  - Response not valid JSON → extracts JSON block from text
  - Empty response → raises with context
"""
import os
import json
import re
import logging

logger = logging.getLogger(__name__)

MODEL = os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')


def chat_completion_json(system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
    """
    Call Groq with the given prompts. Returns a parsed Python dict.
    Always uses JSON mode. Raises on failure with a clear message.
    """
    api_key = os.getenv('GROQ_API_KEY', '').strip()
    if not api_key:
        raise EnvironmentError(
            'GROQ_API_KEY is not set. '
            'Add it in Render → Environment tab. '
            'Get a free key at https://console.groq.com'
        )

    from groq import Groq
    client = Groq(api_key=api_key)

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=temperature,
            response_format={'type': 'json_object'},
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user',   'content': user_prompt}
            ]
        )
    except Exception as e:
        raise RuntimeError(f'Groq API call failed: {e}') from e

    raw = (resp.choices[0].message.content or '').strip()
    if not raw:
        raise ValueError('Groq returned an empty response.')

    logger.debug(f'[LLM] Raw response length={len(raw)}')

    # Primary: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fallback: extract first JSON block from markdown fences
    match = re.search(r'```(?:json)?\s*([\s\S]+?)```', raw)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Last resort: find first { ... } block
    match = re.search(r'(\{[\s\S]+\})', raw)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(f'Could not parse JSON from Groq response. Raw (first 300 chars): {raw[:300]}')
