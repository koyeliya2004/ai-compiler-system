"""
LLM Client -- Multi-Model Router
================================
Each pipeline stage is routed to the best-fit model:

  Stage 1  Intent Extraction    ->  openai/gpt-oss-120b
  Stage 2  System Design        ->  qwen/qwen3-32b
  Stage 3  Schema Generation    ->  meta-llama/llama-4-scout-17b-16e-instruct
  Stage 4  Refinement           ->  openai/gpt-oss-20b
  Stage 5  Validation & Repair  ->  llama-3.1-8b-instant
  Stage 6  Execution            ->  openai/gpt-oss-120b

All models called via Groq (single API key).
Fallback: if primary model fails, tries secondary automatically.
"""
import os
import json
import re
import logging
import time

logger = logging.getLogger(__name__)

# Stage -> [primary_model, fallback_model]
STAGE_MODEL_MAP = {
    1: ["openai/gpt-oss-120b",                      "llama-3.3-70b-versatile"],
    2: ["qwen/qwen3-32b",                            "openai/gpt-oss-20b"],
    3: ["meta-llama/llama-4-scout-17b-16e-instruct", "qwen/qwen3-32b"],
    4: ["openai/gpt-oss-20b",                        "qwen/qwen3-32b"],
    5: ["llama-3.1-8b-instant",                      "openai/gpt-oss-20b"],
    6: ["openai/gpt-oss-120b",                       "llama-3.3-70b-versatile"],
}

MODEL_LABELS = {
    "openai/gpt-oss-120b":                      "GPT-OSS 120B",
    "qwen/qwen3-32b":                           "Qwen3 32B",
    "meta-llama/llama-4-scout-17b-16e-instruct": "Llama-4 Scout 17B",
    "openai/gpt-oss-20b":                       "GPT-OSS 20B",
    "llama-3.1-8b-instant":                     "Llama 3.1 8B",
    "llama-3.3-70b-versatile":                  "Llama 3.3 70B",
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
    """Single model call, returns raw string."""
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
    """Three-layer JSON extraction."""
    if not raw:
        raise ValueError('Empty response')
    # Layer 1: direct parse
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
    # Layer 3: first { ... } block
    m = re.search(r'(\{[\s\S]+\})', raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    raise ValueError('Cannot parse JSON. First 300 chars: ' + raw[:300])


def chat_completion_json(
    system_prompt,
    user_prompt,
    temperature=0.1,
    stage_id=0
):
    """
    Route the call to the right model for this stage.
    Falls back to secondary model if primary fails.
    Returns parsed dict.
    """
    client = _get_groq_client()

    if stage_id in STAGE_MODEL_MAP:
        models = STAGE_MODEL_MAP[stage_id]
        stage_label = 'Stage ' + str(stage_id)
    else:
        default_model = os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')
        models = [default_model, 'llama-3.3-70b-versatile']
        stage_label = 'Stage ' + str(stage_id) + ' (unrouted)'

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
            logger.warning('[LLM] %s FAILED: %s -> %s. Trying fallback...', stage_label, label, str(e))

    raise RuntimeError(
        stage_label + ': all models failed. Last error: ' + str(last_error)
    )
