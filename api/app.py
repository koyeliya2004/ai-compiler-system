"""
AI Compiler System — FastAPI Server
=====================================
Routes:
  GET  /          → Frontend UI (frontend/index.html)
  GET  /health    → Health + config check
  GET  /test-llm  → Quick Groq connectivity test
  POST /compile   → Full 6-stage pipeline
  GET  /docs      → Swagger UI (auto)
"""
import os
import sys
import time
import traceback
import logging
from pathlib import Path

# ━━ Ensure repo root is on sys.path — fixes all import paths on Render ━━
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logging.basicConfig(
    level=os.getenv('PIPELINE_LOG_LEVEL', 'INFO'),
    format='%(asctime)s %(levelname)s %(name)s — %(message)s'
)
logger = logging.getLogger(__name__)

FRONTEND = ROOT / 'frontend' / 'index.html'

app = FastAPI(
    title='AI Compiler System',
    description='Natural language → validated → executable app config. 6-stage pipeline.',
    version='1.0.0'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


# ━━ Global handler — always JSON, never blank 500 ━━
@app.exception_handler(Exception)
async def _global_error(request: Request, exc: Exception):
    logger.error(f'Unhandled: {exc}\n{traceback.format_exc()}')
    return JSONResponse(status_code=500, content={
        'error': type(exc).__name__,
        'detail': str(exc),
        'tip': 'Visit /health and /test-llm to diagnose.'
    })


class CompileRequest(BaseModel):
    prompt: str
    model_config = {'json_schema_extra': {'example': {
        'prompt': 'Build a CRM with login, contacts, dashboard, role-based access, and premium payments.'
    }}}


# ━━ GET / ━━
@app.get('/', response_class=HTMLResponse, include_in_schema=False)
def root():
    if FRONTEND.exists():
        return HTMLResponse(content=FRONTEND.read_text(encoding='utf-8'))
    return HTMLResponse(content=(
        '<html><body style="font:16px sans-serif;padding:40px;background:#0d1117;color:#e6edf3">'
        '<h2>🔧 AI Compiler System</h2>'
        '<p>API is running.</p>'
        '<p><a href="/docs" style="color:#58a6ff">Swagger Docs</a>  |  '
        '<a href="/health" style="color:#58a6ff">Health</a>  |  '
        '<a href="/test-llm" style="color:#58a6ff">Test LLM</a></p>'
        '</body></html>'
    ))


# ━━ GET /health ━━
@app.get('/health', tags=['System'])
def health():
    key_set = bool(os.getenv('GROQ_API_KEY', '').strip())
    return {
        'status': 'ok',
        'python': sys.version,
        'provider': 'groq',
        'model': os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile'),
        'groq_api_key_set': key_set,
        'frontend_exists': FRONTEND.exists(),
        'root_on_path': str(ROOT) in sys.path,
        'warning': None if key_set else '⚠️ GROQ_API_KEY not set — add it in Render → Environment tab'
    }


# ━━ GET /test-llm — quick Groq smoke test ━━
@app.get('/test-llm', tags=['System'])
def test_llm():
    """Calls Groq with a tiny prompt to verify API key + connectivity."""
    if not os.getenv('GROQ_API_KEY', '').strip():
        raise HTTPException(status_code=503, detail='❌ GROQ_API_KEY not set. Add it in Render → Environment tab.')
    try:
        from llm_client import chat_completion_json
        t = time.time()
        result = chat_completion_json(
            system_prompt='Return only valid JSON.',
            user_prompt='Return: {"status": "ok", "message": "Groq is working"}',
            temperature=0.0
        )
        ms = round((time.time() - t) * 1000)
        return {'groq_connected': True, 'response': result, 'latency_ms': ms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'❌ Groq test failed: {type(e).__name__}: {e}')


# ━━ POST /compile — full 6-stage pipeline ━━
@app.post('/compile', tags=['Pipeline'])
def compile_app(req: CompileRequest):
    if not os.getenv('GROQ_API_KEY', '').strip():
        raise HTTPException(status_code=503, detail={
            'error': 'GROQ_API_KEY not configured',
            'fix': 'Render dashboard → your service → Environment → add GROQ_API_KEY',
            'get_key': 'https://console.groq.com (free)'
        })
    if not (req.prompt or '').strip():
        raise HTTPException(status_code=422, detail='prompt cannot be empty')

    started = time.time()
    timings = {}

    # Stage 1
    try:
        from pipeline.stage1_intent_extraction import extract_intent
        t = time.time(); intent = extract_intent(req.prompt)
        timings['stage1_ms'] = round((time.time() - t) * 1000)
        logger.info(f'Stage1 OK {timings["stage1_ms"]}ms')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Stage 1 (Intent Extraction) failed: {e}')

    # Stage 2
    try:
        from pipeline.stage2_system_design import design_system
        t = time.time(); blueprint = design_system(intent)
        timings['stage2_ms'] = round((time.time() - t) * 1000)
        logger.info(f'Stage2 OK {timings["stage2_ms"]}ms')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Stage 2 (System Design) failed: {e}')

    # Stage 3
    try:
        from pipeline.stage3_schema_generation import generate_schemas
        t = time.time(); schemas = generate_schemas(blueprint)
        timings['stage3_ms'] = round((time.time() - t) * 1000)
        logger.info(f'Stage3 OK {timings["stage3_ms"]}ms')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Stage 3 (Schema Generation) failed: {e}')

    # Stage 4 (non-fatal)
    try:
        from pipeline.stage4_refinement import refine_schemas
        t = time.time(); refined = refine_schemas(schemas)
        timings['stage4_ms'] = round((time.time() - t) * 1000)
        logger.info(f'Stage4 OK {timings["stage4_ms"]}ms')
    except Exception as e:
        logger.warning(f'Stage4 fallback: {e}'); refined = schemas; timings['stage4_ms'] = 0

    app_name = blueprint.get('app_name') or intent.get('app_name', 'Generated App')
    output = {
        'app_name': app_name,
        'pipeline_version': '1.0.0',
        'intent_raw': intent,
        'blueprint': blueprint,
        'schemas': refined,
    }

    # Stage 5
    try:
        from pipeline.stage5_validation_repair import validate_pipeline_output, repair_pipeline_output
        t = time.time()
        validation = validate_pipeline_output(output)
        if not validation['valid']:
            output = repair_pipeline_output(output)
            validation = validate_pipeline_output(output)
        timings['stage5_ms'] = round((time.time() - t) * 1000)
        logger.info(f'Stage5 OK valid={validation["valid"]} {timings["stage5_ms"]}ms')
    except Exception as e:
        logger.warning(f'Stage5: {e}')
        validation = {'valid': False, 'errors': [str(e)], 'warnings': []}
        timings['stage5_ms'] = 0

    # Stage 6
    try:
        from pipeline.stage6_execution import check_execution_readiness
        t = time.time(); runtime = check_execution_readiness(output)
        timings['stage6_ms'] = round((time.time() - t) * 1000)
        logger.info(f'Stage6 OK executable={runtime["is_executable"]} {timings["stage6_ms"]}ms')
    except Exception as e:
        logger.warning(f'Stage6: {e}')
        runtime = {'is_executable': False, 'issues': [str(e)], 'preview': {'boot_log': []}}
        timings['stage6_ms'] = 0

    # Runtime artifacts
    try:
        from runtime.minimal_runtime import generate_openapi_stub, generate_db_migration_stub
        openapi_stub = generate_openapi_stub(output)
        db_migration = generate_db_migration_stub(output)
    except Exception as e:
        logger.warning(f'Artifacts: {e}'); openapi_stub = {}; db_migration = ''

    total_ms = round((time.time() - started) * 1000)
    logger.info(f'/compile done {total_ms}ms executable={runtime.get("is_executable")}')

    return {
        'success': validation.get('valid', False),
        'app_name': app_name,
        'validation': validation,
        'runtime': runtime,
        'artifacts': {
            'openapi_stub': openapi_stub,
            'db_migration_preview': db_migration[:2000] if db_migration else ''
        },
        'output': output,
        'meta': {
            'total_ms': total_ms,
            'stage_timings': timings,
            'assumptions': intent.get('assumptions', []),
            'clarifications': intent.get('clarifications_needed', [])
        }
    }
