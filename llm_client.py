"""
LLM Client — Groq Only (groq>=0.11.0)
========================================
Do NOT pass proxies= to Groq() — removed in groq 0.11+
"""
import os
import json
import re
import logging

logger = logging.getLogger(__name__)


def chat_completion_json(system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
    """
    Call Groq, return parsed dict. Raises clear errors on failure.
    """
    api_key = os.getenv('GROQ_API_KEY', '').strip()
    if not api_key:
        raise EnvironmentError(
            'GROQ_API_KEY is not set. '
            'Go to Render dashboard → your service → Environment tab → add GROQ_API_KEY. '
            'Free key at https://console.groq.com'
        )

    model = os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')

    # Import here — never at module level
    from groq import Groq

    # IMPORTANT: do NOT pass proxies=, timeout= as kwargs — removed in groq 0.11
    client = Groq(api_key=api_key)

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt}
            ]
        )
    except Exception as e:
        raise RuntimeError(f'Groq API call failed: {type(e).__name__}: {e}') from e

    raw = (response.choices[0].message.content or '').strip()
    if not raw:
        raise ValueError('Groq returned empty response')

    logger.debug(f'[LLM] response length={len(raw)}')

    # Layer 1: direct JSON parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Layer 2: strip markdown fences
    m = re.search(r'```(?:json)?\s*([\s\S]+?)```', raw)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Layer 3: find first { ... } block
    m = re.search(r'(\{[\s\S]+\})', raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    raise ValueError(f'Cannot parse JSON from Groq response. First 300 chars: {raw[:300]}')
