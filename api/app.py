"""
FastAPI Web Interface
=====================
Endpoints:
  GET  /              - Frontend UI
  GET  /health        - Health check
  POST /compile       - Full 6-stage pipeline
  POST /validate      - Validate a provided output
  GET  /schema/{name} - Retrieve a schema contract
  GET  /docs          - Swagger UI
"""

import os
import time
import json
import traceback
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.getenv('PIPELINE_LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

app = FastAPI(
    title='AI Compiler System',
    description='Natural language → structured config → validated → executable app generation pipeline',
    version='1.0.0'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend' / 'index.html'


# ─── Global exception handler so 500s return JSON with the real error ────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error(f'[API] Unhandled exception: {exc}\n{tb}')
    return JSONResponse(
        status_code=500,
        content={
            'error': type(exc).__name__,
            'detail': str(exc),
            'hint': 'Check that GROQ_API_KEY is set in your Render environment variables.'
        }
    )


class CompileRequest(BaseModel):
    prompt: str

    class Config:
        json_schema_extra = {
            'example': {
                'prompt': 'Build a CRM with login, contacts, dashboard, role-based access, and premium plan with payments.'
            }
        }


class ValidateRequest(BaseModel):
    output: dict


# ─── Root ────────────────────────────────────────────────────────────────────
@app.get('/', response_class=HTMLResponse, include_in_schema=False)
def root():
    if FRONTEND.exists():
        return HTMLResponse(content=FRONTEND.read_text(), status_code=200)
    return HTMLResponse(content="""
<!DOCTYPE html><html><head><title>AI Compiler System</title>
<style>body{font-family:sans-serif;background:#0d1117;color:#e6edf3;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  min-height:100vh;gap:20px;} a{color:#58a6ff;} </style></head>
<body><h1>AI Compiler System</h1>
<p>API is running. <a href="/docs">Open Swagger UI</a> | <a href="/health">Health Check</a></p>
</body></html>""", status_code=200)


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get('/health', tags=['System'])
def health():
    api_key_set = bool(os.getenv('GROQ_API_KEY'))
    return {
        'status': 'ok',
        'service': 'ai-compiler-system',
        'version': '1.0.0',
        'provider': os.getenv('LLM_PROVIDER', 'groq'),
        'model': os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile'),
        'groq_api_key_set': api_key_set,
        'warning': None if api_key_set else 'GROQ_API_KEY is NOT set — /compile will fail!'
    }


# ─── Schema retrieval ─────────────────────────────────────────────────────────
@app.get('/schema/{name}', tags=['Schemas'])
def get_schema(name: str):
    schema_map = {
        'intent': 'intent_schema.json',
        'blueprint': 'app_blueprint_schema.json',
        'output': 'output_schema.json'
    }
    if name not in schema_map:
        raise HTTPException(status_code=404, detail=f"Schema '{name}' not found. Available: {list(schema_map.keys())}")
    schema_path = ROOT / 'schemas' / schema_map[name]
    if not schema_path.exists():
        raise HTTPException(status_code=404, detail=f"Schema file missing: {schema_map[name]}")
    return json.loads(schema_path.read_text())


# ─── Validate ─────────────────────────────────────────────────────────────────
@app.post('/validate', tags=['Pipeline'])
def validate_output(req: ValidateRequest):
    from pipeline.stage5_validation_repair import validate_pipeline_output
    return validate_pipeline_output(req.output)


# ─── Compile — full 6-stage pipeline ─────────────────────────────────────────
@app.post('/compile', tags=['Pipeline'])
def compile_app(req: CompileRequest):
    """
    Full 6-stage pipeline: NL prompt → validated, executable app config.
    """
    # Check API key early — give a clear error instead of a cryptic 500
    if not os.getenv('GROQ_API_KEY') and not os.getenv('OPENAI_API_KEY'):
        raise HTTPException(
            status_code=503,
            detail={
                'error': 'No LLM API key configured',
                'fix': 'Set GROQ_API_KEY in your Render environment variables.',
                'get_key': 'https://console.groq.com (free)'
            }
        )

    # Lazy imports — prevents startup crash if a stage has a syntax error
    from pipeline.stage1_intent_extraction import extract_intent
    from pipeline.stage2_system_design import design_system
    from pipeline.stage3_schema_generation import generate_schemas
    from pipeline.stage4_refinement import refine_schemas
    from pipeline.stage5_validation_repair import validate_pipeline_output, repair_pipeline_output
    from pipeline.stage6_execution import check_execution_readiness
    from runtime.minimal_runtime import generate_openapi_stub, generate_db_migration_stub

    started = time.time()
    stage_latencies = {}
    repair_counts = {f'stage{i}': 0 for i in range(1, 7)}

    logger.info(f'[API] /compile → {req.prompt[:80]}')

    try:
        t = time.time()
        intent = extract_intent(req.prompt)
        stage_latencies['stage1_ms'] = round((time.time() - t) * 1000, 2)
        logger.info(f'[API] Stage 1 done in {stage_latencies["stage1_ms"]}ms')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Stage 1 (Intent) failed: {e}')

    try:
        t = time.time()
        blueprint = design_system(intent)
        stage_latencies['stage2_ms'] = round((time.time() - t) * 1000, 2)
        logger.info(f'[API] Stage 2 done in {stage_latencies["stage2_ms"]}ms')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Stage 2 (Design) failed: {e}')

    try:
        t = time.time()
        schemas = generate_schemas(blueprint)
        stage_latencies['stage3_ms'] = round((time.time() - t) * 1000, 2)
        logger.info(f'[API] Stage 3 done in {stage_latencies["stage3_ms"]}ms')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Stage 3 (Schemas) failed: {e}')

    try:
        t = time.time()
        refined = refine_schemas(schemas)
        stage_latencies['stage4_ms'] = round((time.time() - t) * 1000, 2)
        logger.info(f'[API] Stage 4 done in {stage_latencies["stage4_ms"]}ms')
    except Exception as e:
        logger.warning(f'[API] Stage 4 failed (using unrefined schemas): {e}')
        refined = schemas  # fallback: use unrefinened schemas
        stage_latencies['stage4_ms'] = 0

    final_output = {
        'app_name': blueprint.get('app_name', intent.get('app_name', 'Generated App')),
        'pipeline_version': '1.0.0',
        'intent': {
            'app_type': intent.get('app_type', 'Other'),
            'features_count': len(intent.get('features', [])),
            'entities_count': len(intent.get('entities', [])),
            'roles': [r.get('name') for r in intent.get('roles', [])],
        },
        'intent_raw': intent,
        'blueprint': blueprint,
        'schemas': refined,
        'metadata': {
            'total_latency_ms': 0,
            'stage_latencies': stage_latencies,
            'repair_counts': repair_counts,
            'assumptions': intent.get('assumptions', []),
            'warnings': [],
            'is_executable': False
        }
    }

    try:
        t = time.time()
        validation = validate_pipeline_output(final_output)
        stage_latencies['stage5_ms'] = round((time.time() - t) * 1000, 2)
        if not validation['valid']:
            logger.warning(f"[API] Stage 5: {len(validation['errors'])} errors — repairing...")
            t = time.time()
            final_output = repair_pipeline_output(final_output)
            stage_latencies['stage5_repair_ms'] = round((time.time() - t) * 1000, 2)
            repair_counts['stage5'] += 1
            validation = validate_pipeline_output(final_output)
    except Exception as e:
        logger.warning(f'[API] Stage 5 failed: {e}')
        validation = {'valid': False, 'errors': [str(e)], 'warnings': []}

    try:
        t = time.time()
        runtime = check_execution_readiness(final_output)
        stage_latencies['stage6_ms'] = round((time.time() - t) * 1000, 2)
    except Exception as e:
        logger.warning(f'[API] Stage 6 failed: {e}')
        runtime = {'is_executable': False, 'issues': [str(e)], 'preview': {'boot_log': []}}

    try:
        openapi_stub = generate_openapi_stub(final_output)
        db_migration = generate_db_migration_stub(final_output)
    except Exception as e:
        logger.warning(f'[API] Runtime artifact generation failed: {e}')
        openapi_stub = {}
        db_migration = ''

    final_output['metadata']['is_executable'] = runtime.get('is_executable', False)
    final_output['metadata']['total_latency_ms'] = round((time.time() - started) * 1000, 2)
    final_output['metadata']['stage_latencies'] = stage_latencies

    return {
        'success': validation.get('valid', False) and runtime.get('is_executable', False),
        'app_name': final_output['app_name'],
        'validation': validation,
        'runtime': runtime,
        'artifacts': {
            'openapi_stub': openapi_stub,
            'db_migration_preview': (db_migration[:1000] + '...') if len(db_migration) > 1000 else db_migration
        },
        'output': final_output,
    }
