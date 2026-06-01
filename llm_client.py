"""
LLM Client — Multi-Model Router
================================
Each pipeline stage is routed to the best-fit model:

  Stage 1  Intent Extraction    →  openai/gpt-oss-120b          (best at understanding nuance)
  Stage 2  System Design        →  qwen/qwen3-32b               (strong at structured reasoning)
  Stage 3  Schema Generation    →  meta-llama/llama-4-scout-17b (fast, good at structured JSON)
  Stage 4  Refinement           →  openai/gpt-oss-20b           (fast + smart for consistency fixes)
  Stage 5  Validation & Repair  →  llama-3.1-8b-instant         (ultra-fast for rule-based checks)
  Stage 6  Execution            →  openai/gpt-oss-120b          (most reliable for final verdict)

All models are called via Groq (single API key, no extra cost).
Fallback chain: if a model fails, tries next best model for that stage.
"""
import os
import json
import re
import logging
import time

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────
STAGE → MODEL ROUTING TABLE
# ────────────────────────────────────────────────────────────────────────
STAGE_MODEL_MAP = {
    # stage_id : [primary_model, fallback_model]
    1: ["openai/gpt-oss-120b",                    "llama-3.3-70b-versatile"],   # Intent  — needs deep NL understanding
    2: ["qwen/qwen3-32b",                          "openai/gpt-oss-20b"],        # Design  — strong structured reasoning
    3: ["meta-llama/llama-4-scout-17b-16e-instruct","qwen/qwen3-32b"],          # Schema  — fast JSON generation
    4: ["openai/gpt-oss-20b",                      "qwen/qwen3-32b"],           # Refine  — fast consistency checks
    5: ["llama-3.1-8b-instant",                    "openai/gpt-oss-20b"],       # Validate— ultra-fast rule checks
    6: ["openai/gpt-oss-120b",                     "llama-3.3-70b-versatile"],  # Execute — authoritative final pass
}

# Human-readable names for logging
MODEL_LABELS = {
    "openai/gpt-oss-120b":                     "GPT-OSS 120B",
    "qwen/qwen3-32b":                          "Qwen3 32B",
    "meta-llama/llama-4-scout-17b-16e-instruct": "Llama-4 Scout 17B",
    "openai/gpt-oss-20b":                      "GPT-OSS 20B",
    "llama-3.1-8b-instant":                    "Llama 3.1 8B",
    "llama-3.3-70b-versatile":                 "Llama 3.3 70B",
}


def _get_groq_client():
    api_key = os.getenv('GROQ_API_KEY', '').strip()
    if not api_key:
        raise EnvironmentError(
            'GROQ_API_KEY is not set. '
            'Go to Render dashboard → your service → Environment tab → add GROQ_API_KEY. '
            'Free key at https://console.groq.com'
        )
    from groq import Groq
    return Groq(api_key=api_key)


def _call_model(client, model: str, system_prompt: str, user_prompt: str, temperature: float) -> str:
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


def _parse_json(raw: str) -> dict:
    """Three-layer JSON extraction."""
    if not raw:
        raise ValueError('Empty response')
    # Layer 1: direct
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
    raise ValueError(f'Cannot parse JSON. First 300 chars: {raw[:300]}')


def chat_completion_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    stage_id: int = 0          # 1–6  — which pipeline stage is calling
) -> dict:
    """
    Route the call to the right model for this stage.
    If primary model fails, automatically falls back to secondary.
    Returns parsed dict. Raises on total failure.
    """
    client = _get_groq_client()

    # Determine model list for this stage
    if stage_id in STAGE_MODEL_MAP:
        models = STAGE_MODEL_MAP[stage_id]
        stage_label = f"Stage {stage_id}"
    else:
        # Fallback: use env var or default
        default_model = os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')
        models = [default_model, 'llama-3.3-70b-versatile']
        stage_label = f"Stage {stage_id} (unrouted)"

    last_error = None
    for attempt, model in enumerate(models):
        label = MODEL_LABELS.get(model, model)
        try:
            t0 = time.time()
            logger.info(f'[LLM] {stage_label} → {label} (attempt {attempt+1})')
            raw = _call_model(client, model, system_prompt, user_prompt, temperature)
            elapsed = int((time.time() - t0) * 1000)
            result = _parse_json(raw)
            # Inject routing metadata so callers can log it
            result['__model_used__'] = model
            result['__model_label__'] = label
            result['__stage_ms__'] = elapsed
            logger.info(f'[LLM] {stage_label} ✔ {label} in {elapsed}ms')
            return result
        except Exception as e:
            last_error = e
            logger.warning(f'[LLM] {stage_label} ✗ {label} failed: {e}. Trying fallback...')

    raise RuntimeError(
        f'{stage_label}: all models failed. Last error: {last_error}'
    )
