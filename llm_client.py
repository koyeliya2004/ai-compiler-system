"""
LLM Client
==========
Unified client supporting Groq (default) and OpenAI.
All pipeline stages use this for consistent LLM access.
"""
import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

PROVIDER = os.getenv('LLM_PROVIDER', 'groq').lower()
MODEL = os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')


def chat_completion_json(system_prompt: str, user_prompt: str, temperature: float = 0.1) -> dict:
    """
    Call LLM with JSON mode. Returns parsed dict.
    Supports: groq (default), openai
    """
    if PROVIDER == 'openai':
        return _openai_json(system_prompt, user_prompt, temperature)
    return _groq_json(system_prompt, user_prompt, temperature)


def _groq_json(system_prompt: str, user_prompt: str, temperature: float) -> dict:
    from groq import Groq
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        raise EnvironmentError(
            'GROQ_API_KEY environment variable is not set. '
            'Get a free key at https://console.groq.com'
        )
    client = Groq(api_key=api_key)
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=temperature,
        response_format={'type': 'json_object'},
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ]
    )
    raw = resp.choices[0].message.content
    logger.debug(f'[LLM] Groq response length={len(raw)}')
    return json.loads(raw)


def _openai_json(system_prompt: str, user_prompt: str, temperature: float) -> dict:
    from openai import OpenAI
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        raise EnvironmentError('OPENAI_API_KEY environment variable is not set.')
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=os.getenv('LLM_MODEL', 'gpt-4o-mini'),
        temperature=temperature,
        response_format={'type': 'json_object'},
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ]
    )
    raw = resp.choices[0].message.content
    logger.debug(f'[LLM] OpenAI response length={len(raw)}')
    return json.loads(raw)
