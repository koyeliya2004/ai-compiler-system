"""
FastAPI Web Interface
=====================
Endpoints:
  GET  /              — Frontend UI (HTML demo page)
  GET  /health        — Health check
  POST /compile       — Full pipeline: NL prompt → validated app config
  POST /validate      — Validate a provided output
  GET  /schema/{name} — Retrieve a schema contract
  GET  /docs          — Swagger UI
"""

import os
import time
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
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


class CompileRequest(BaseModel):
    prompt: str

    class Config:
        json_schema_extra = {
            'example': {
                'prompt': 'Build a CRM with login, contacts, dashboard, role-based access, and premium plan with payments. Admins can see analytics.'
            }
        }


class ValidateRequest(BaseModel):
    output: dict


# ─── Root: serve frontend UI ────────────────────────────────────────────────

@app.get('/', response_class=HTMLResponse, include_in_schema=False)
def root():
    """Serve the frontend demo UI."""
    if FRONTEND.exists():
        return HTMLResponse(content=FRONTEND.read_text(), status_code=200)
    # Fallback landing page if frontend file missing
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI Compiler System</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3;
           display: flex; flex-direction: column; align-items: center;
           justify-content: center; min-height: 100vh; gap: 24px; padding: 24px; }
    h1 { font-size: 2rem; color: #58a6ff; }
    p  { color: #8b949e; max-width: 480px; text-align: center; line-height: 1.6; }
    .links { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }
    a  { background: #21262d; color: #58a6ff; padding: 10px 20px;
         border-radius: 8px; text-decoration: none; border: 1px solid #30363d;
         transition: background 0.2s; }
    a:hover { background: #30363d; }
    .badge { background: #238636; color: #fff; padding: 4px 12px;
             border-radius: 20px; font-size: 0.8rem; }
  </style>
</head>
<body>
  <span class="badge">✅ Online</span>
  <h1>🧠 AI Compiler System</h1>
  <p>Natural language → structured config → validated → executable app generation pipeline</p>
  <div class="links">
    <a href="/docs">📚 Swagger UI</a>
    <a href="/health">🟢 Health Check</a>
    <a href="/redoc">📖 API Docs</a>
  </div>
</body>
</html>
""", status_code=200)


# ─── System ──────────────────────────────────────────────────────────────────

@app.get('/health', tags=['System'])
def health():
    """Health check."""
    return {
        'status': 'ok',
        'service': 'ai-compiler-system',
        'version': '1.0.0',
        'provider': os.getenv('LLM_PROVIDER', 'groq'),
        'model': os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')
    }


# ─── Schemas ─────────────────────────────────────────────────────────────────

@app.get('/schema/{name}', tags=['Schemas'])
def get_schema(name: str):
    """Retrieve a named JSON Schema contract. Available: intent, blueprint, output"""
    schema_map = {
        'intent': 'intent_schema.json',
        'blueprint': 'app_blueprint_schema.json',
        'output': 'output_schema.json'
    }
    if name not in schema_map:
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{name}' not found. Available: {list(schema_map.keys())}"
        )
    schema_path = ROOT / 'schemas' / schema_map[name]
    return json.loads(schema_path.read_text())


# ─── Pipeline ────────────────────────────────────────────────────────────────

@app.post('/validate', tags=['Pipeline'])
def validate_output(req: ValidateRequest):
    """Validate a provided pipeline output against all schema contracts."""
    from pipeline.stage5_validation_repair import validate_pipeline_output
    return validate_pipeline_output(req.output)


@app.post('/compile', tags=['Pipeline'])
def compile_app(req: CompileRequest):
    """
    Full 6-stage pipeline: Natural language prompt → validated, executable app config.

    Stages:
    1. Intent Extraction  — NL → IntentSchema
    2. System Design      — Intent → AppBlueprint
    3. Schema Generation  — Blueprint → UI + API + DB + Auth
    4. Refinement         — Cross-layer consistency
    5. Validation+Repair  — Schema contracts + targeted repair
    6. Execution Aware    — Boot readiness gate
    """
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

    t = time.time(); intent = extract_intent(req.prompt)
    stage_latencies['stage1_intent_ms'] = round((time.time()-t)*1000, 2)

    t = time.time(); blueprint = design_system(intent)
    stage_latencies['stage2_design_ms'] = round((time.time()-t)*1000, 2)

    t = time.time(); schemas = generate_schemas(blueprint)
    stage_latencies['stage3_schemas_ms'] = round((time.time()-t)*1000, 2)

    t = time.time(); refined = refine_schemas(schemas)
    stage_latencies['stage4_refine_ms'] = round((time.time()-t)*1000, 2)

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

    t = time.time()
    validation = validate_pipeline_output(final_output)
    stage_latencies['stage5_validate_ms'] = round((time.time()-t)*1000, 2)

    if not validation['valid']:
        logger.warning(f"[API] Stage 5: {len(validation['errors'])} errors — repairing...")
        t = time.time()
        final_output = repair_pipeline_output(final_output)
        stage_latencies['stage5_repair_ms'] = round((time.time()-t)*1000, 2)
        repair_counts['stage5'] += 1
        validation = validate_pipeline_output(final_output)

    t = time.time()
    runtime = check_execution_readiness(final_output)
    stage_latencies['stage6_execution_ms'] = round((time.time()-t)*1000, 2)

    openapi_stub = generate_openapi_stub(final_output)
    db_migration = generate_db_migration_stub(final_output)

    final_output['metadata']['is_executable'] = runtime['is_executable']
    final_output['metadata']['total_latency_ms'] = round((time.time()-started)*1000, 2)
    final_output['metadata']['stage_latencies'] = stage_latencies

    return {
        'success': validation.get('valid', False) and runtime.get('is_executable', False),
        'app_name': final_output['app_name'],
        'validation': validation,
        'runtime': runtime,
        'artifacts': {
            'openapi_stub': openapi_stub,
            'db_migration_preview': db_migration[:1000] + '...' if len(db_migration) > 1000 else db_migration
        },
        'output': final_output,
    }
