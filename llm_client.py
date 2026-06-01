"""
LLM Client — Provider-agnostic wrapper
=======================================
Supports: Groq (default, free), OpenAI (fallback)

Set environment variables:
  LLM_PROVIDER=groq          (default)
  LLM_MODEL=llama-3.3-70b-versatile  (default)
  GROQ_API_KEY=gsk_...       (required for groq)
  OPENAI_API_KEY=sk-...      (required for openai)
"""

import os
import json
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

PROVIDER = os.getenv('LLM_PROVIDER', 'groq').lower()
MODEL = os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')


def get_client():
    """Return the appropriate LLM client based on LLM_PROVIDER env var."""
    if PROVIDER == 'groq':
        from groq import Groq
        api_key = os.getenv('GROQ_API_KEY')
        if not api_key:
            raise ValueError('GROQ_API_KEY environment variable not set.')
        return Groq(api_key=api_key)
    elif PROVIDER == 'openai':
        from openai import OpenAI
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError('OPENAI_API_KEY environment variable not set.')
        return OpenAI(api_key=api_key)
    else:
        raise ValueError(f'Unknown LLM_PROVIDER: {PROVIDER}. Use groq or openai.')


def chat_completion(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    model: Optional[str] = None
) -> str:
    """
    Provider-agnostic chat completion.
    Returns the raw string content of the response.
    """
    client = get_client()
    chosen_model = model or MODEL

    logger.debug(f'[LLM] Provider={PROVIDER}, Model={chosen_model}, temp={temperature}')

    response = client.chat.completions.create(
        model=chosen_model,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def chat_completion_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    model: Optional[str] = None
) -> dict:
    """
    Like chat_completion but parses and returns a JSON dict.
    Strips markdown code fences if present.
    Raises ValueError if response is not valid JSON.
    """
    raw = chat_completion(system_prompt, user_prompt, temperature, max_tokens, model)

    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        cleaned = '\n'.join(lines[1:-1] if lines[-1].strip() == '```' else lines[1:])

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f'[LLM] JSON parse failed: {e}\nRaw response: {raw[:500]}')
        raise ValueError(f'LLM returned invalid JSON: {e}') from e
