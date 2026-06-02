"""
LLM Client -- Multi-Model Router
================================
Stage routing (all via Groq free tier):

  Stage 1  Intent Extraction   ->  llama-3.3-70b-versatile
  Stage 2  System Design       ->  llama-3.3-70b-versatile
  Stage 3  Schema Generation   ->  llama-3.3-70b-versatile
  Stage 4  Refinement          ->  deterministic (no LLM)
  Stage 5  Validation & Repair ->  deterministic (no LLM)
  Stage 6  Execution           ->  deterministic (no LLM)

Fallback: gemma2-9b-it
"""
import os
import json
import re
import logging
import time

logger = logging.getLogger(__name__)

# All valid Groq model IDs as of 2025
STAGE_MODEL_MAP = {
    1: ["llama-3.3-70b-versatile",  "gemma2-9b-it"],
    2: ["llama-3.3-70b-versatile",  "gemma2-9b-it"],
    3: ["llama-3.3-70b-versatile",  "gemma2-9b-it"],
    4: ["llama-3.3-70b-versatile",  "gemma2-9b-it"],
    5: ["llama-3.1-8b-instant",     "gemma2-9b-it"],
    6: ["llama-3.3-70b-versatile",  "gemma2-9b-it"],
}

MODEL_LABELS = {
    "llama-3.3-70b-versatile": "Llama 3.3 70B",
    "llama-3.1-8b-instant":    "Llama 3.1 8B",
    "gemma2-9b-it":            "Gemma2 9B",
}


def _get_groq_client():
    api_key = os.getenv('GROQ_API_KEY', '').strip()
    if not api_key:
        raise EnvironmentError(
            'GROQ_API_KEY is not set. '
            'Go to Render dashboard -> your service -> Environment tab -> add GROQ_API_KEY. '
            'Free key at https://console.groq.com'
        )
    from groq import Groq
    return Groq(api_key=api_key)


def _call_model(client, model, system_prompt, user_prompt, temperature):
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ]
    )
    return (response.choices[0].message.content or '').strip()


def _parse_json(raw):
    if not raw:
        raise ValueError('Empty response')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*([\s\S]+?)```', raw)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    m = re.search(r'(\{[\s\S]+\})', raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    raise ValueError('Cannot parse JSON. First 300 chars: ' + raw[:300])


def chat_completion_json(system_prompt, user_prompt, temperature=0.1, stage_id=0):
    client = _get_groq_client()
    models = STAGE_MODEL_MAP.get(stage_id, ["llama-3.3-70b-versatile", "gemma2-9b-it"])
    stage_label = f'Stage {stage_id}'
    last_error = None

    for attempt, model in enumerate(models):
        label = MODEL_LABELS.get(model, model)
        try:
            t0 = time.time()
            logger.info('[LLM] %s -> %s (attempt %d)', stage_label, label, attempt + 1)
            raw = _call_model(client, model, system_prompt, user_prompt, temperature)
            elapsed = int((time.time() - t0) * 1000)
            result = _parse_json(raw)
            result['__model_used__']  = model
            result['__model_label__'] = label
            result['__stage_ms__']    = elapsed
            logger.info('[LLM] %s OK: %s in %dms', stage_label, label, elapsed)
            return result
        except Exception as e:
            last_error = e
            logger.warning('[LLM] %s FAILED: %s -> %s', stage_label, label, str(e))

    raise RuntimeError(f'{stage_label}: all models failed. Last error: {last_error}')
