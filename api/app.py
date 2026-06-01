"""
FastAPI Web Interface
=====================
Exposes the AI Compiler pipeline as a REST API.

Endpoints:
  GET  /health           — Health check
  POST /compile          — Full pipeline: NL prompt → validated app config
  POST /validate         — Validate a provided output without full pipeline
  GET  /schema/{name}    — Retrieve a schema contract by name

Run with: uvicorn api.app:app --reload
"""

import os
import time
import json
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.getenv('PIPELINE_LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

app = FastAPI(
    title='AI Compiler System',
    description='Natural language → structured config → validated → executable app generation pipeline',
    version='0.1.0'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

ROOT = Path(__file__).resolve().parents[1]


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


@app.get('/health', tags=['System'])
def health():
    """Health check endpoint."""
    return {'status': 'ok', 'service': 'ai-compiler-system', 'version': '0.1.0'}


@app.get('/schema/{name}', tags=['Schemas'])
def get_schema(name: str):
    """Retrieve a named JSON Schema contract. Available: intent, blueprint, output"""
    schema_map = {
        'intent': 'intent_schema.json',
        'blueprint': 'app_blueprint_schema.json',
        'output': 'output_schema.json'
    }
    if name not in schema_map:
        raise HTTPException(status_code=404, detail=f"Schema '{name}' not found. Available: {list(schema_map.keys())}")
    schema_path = ROOT / 'schemas' / schema_map[name]
    return json.loads(schema_path.read_text())


@app.post('/validate', tags=['Pipeline'])
def validate_output(req: ValidateRequest):
    """Validate a provided pipeline output against all schema contracts."""
    from pipeline.stage5_validation_repair import validate_pipeline_output
    return validate_pipeline_output(req.output)


@app.post('/compile', tags=['Pipeline'])
def compile_app(req: CompileRequest):
    """
    Full pipeline: Natural language prompt → validated, executable app configuration.

    Runs all 6 stages:
    1. Intent Extraction
    2. System Design
    3. Schema Generation (UI, API, DB, Auth)
    4. Refinement (cross-layer consistency)
    5. Validation + Repair
    6. Execution Awareness
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

    logger.info(f"[API] /compile called: {req.prompt[:80]}...")

    t = time.time(); intent = extract_intent(req.prompt); stage_latencies['stage1_intent_ms'] = round((time.time()-t)*1000, 2)
    t = time.time(); blueprint = design_system(intent); stage_latencies['stage2_design_ms'] = round((time.time()-t)*1000, 2)
    t = time.time(); schemas = generate_schemas(blueprint); stage_latencies['stage3_schemas_ms'] = round((time.time()-t)*1000, 2)
    t = time.time(); refined = refine_schemas(schemas); stage_latencies['stage4_refine_ms'] = round((time.time()-t)*1000, 2)

    final_output = {
        'app_name': blueprint.get('app_name', intent.get('app_name', 'Generated App')),
        'pipeline_version': '0.1.0',
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
        logger.warning(f"[API] Stage 5: {len(validation['errors'])} errors found, running repair...")
        t = time.time()
        final_output = repair_pipeline_output(final_output)
        stage_latencies['stage5_repair_ms'] = round((time.time()-t)*1000, 2)
        repair_counts['stage5'] += 1
        validation = final_output['metadata'].get('last_validation', validate_pipeline_output(final_output))

    t = time.time()
    runtime = check_execution_readiness(final_output)
    stage_latencies['stage6_execution_ms'] = round((time.time()-t)*1000, 2)

    openapi_stub = generate_openapi_stub(final_output)
    db_migration = generate_db_migration_stub(final_output)

    final_output['metadata']['is_executable'] = runtime['is_executable']
    final_output['metadata']['total_latency_ms'] = round((time.time()-started)*1000, 2)
    final_output['metadata']['stage_latencies'] = stage_latencies

    return {
        'success': validation['valid'] and runtime['is_executable'],
        'app_name': final_output['app_name'],
        'validation': validation,
        'runtime': runtime,
        'artifacts': {
            'openapi_stub': openapi_stub,
            'db_migration_preview': db_migration[:1000] + '...' if len(db_migration) > 1000 else db_migration
        },
        'output': final_output,
    }
