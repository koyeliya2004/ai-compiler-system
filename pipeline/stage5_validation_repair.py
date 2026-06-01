"""
Stage 5 — Validation + Repair (deterministic, zero LLM calls)
Checks structural completeness and fills missing fields in Python.
"""
import logging

logger = logging.getLogger(__name__)


def validate_pipeline_output(output: dict) -> dict:
    """Check that required fields exist. Returns validation result dict."""
    errors = []
    warnings = []

    schemas = output.get('schemas') or {}
    if isinstance(schemas, dict) and 'repaired_schemas' in schemas:
        schemas = schemas['repaired_schemas']

    ui = schemas.get('ui_config') or {}
    api = schemas.get('api_config') or {}
    db = schemas.get('db_schema') or {}
    auth = schemas.get('auth_config') or {}

    # Required checks
    if not ui.get('pages'):
        errors.append('ui_config.pages is empty')
    if not api.get('endpoints'):
        errors.append('api_config.endpoints is empty')
    if not db.get('tables'):
        errors.append('db_schema.tables is empty')
    if not auth.get('strategy'):
        warnings.append('auth_config.strategy not set')

    # Soft checks
    pages = ui.get('pages', [])
    if len(pages) < 2:
        warnings.append('Only 1 page in ui_config — may be incomplete')

    endpoints = api.get('endpoints', [])
    if len(endpoints) < 3:
        warnings.append('Fewer than 3 API endpoints — may be incomplete')

    tables = db.get('tables', [])
    if len(tables) < 2:
        warnings.append('Fewer than 2 DB tables — may be incomplete')

    valid = len(errors) == 0
    return {'valid': valid, 'errors': errors, 'warnings': warnings}


def repair_pipeline_output(output: dict) -> dict:
    """Fill in minimal scaffolding for any missing required fields. No LLM calls."""
    schemas = output.get('schemas') or {}
    if isinstance(schemas, dict) and 'repaired_schemas' in schemas:
        schemas = schemas['repaired_schemas']

    app_name = output.get('app_name', 'App')

    # Repair ui_config
    ui = schemas.get('ui_config') or {}
    if not ui.get('pages'):
        ui['pages'] = [
            {'name': 'Home', 'path': '/', 'components': ['HeroSection']},
            {'name': 'Dashboard', 'path': '/dashboard', 'components': ['DataTable']}
        ]
    schemas['ui_config'] = ui

    # Repair api_config
    api = schemas.get('api_config') or {}
    if not api.get('endpoints'):
        api['endpoints'] = [
            {'method': 'POST', 'path': '/api/v1/auth/login', 'auth_required': False},
            {'method': 'GET',  'path': '/api/v1/items', 'auth_required': True},
            {'method': 'POST', 'path': '/api/v1/items', 'auth_required': True}
        ]
    if not api.get('base_path'):
        api['base_path'] = '/api/v1'
    schemas['api_config'] = api

    # Repair db_schema
    db = schemas.get('db_schema') or {}
    if not db.get('tables'):
        db['tables'] = [
            {'name': 'users', 'columns': [
                {'name': 'id', 'type': 'UUID', 'primary_key': True, 'nullable': False},
                {'name': 'email', 'type': 'VARCHAR(255)', 'nullable': False, 'unique': True},
                {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False, 'default': 'NOW()'}
            ]},
            {'name': 'items', 'columns': [
                {'name': 'id', 'type': 'UUID', 'primary_key': True, 'nullable': False},
                {'name': 'user_id', 'type': 'UUID', 'nullable': False},
                {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False, 'default': 'NOW()'}
            ]}
        ]
    schemas['db_schema'] = db

    # Repair auth_config
    auth = schemas.get('auth_config') or {}
    if not auth.get('strategy'):
        auth['strategy'] = 'jwt'
    if not auth.get('roles'):
        auth['roles'] = ['user', 'admin']
    schemas['auth_config'] = auth

    output['schemas'] = schemas
    logger.info('Stage5 repair done (deterministic)')
    return output
