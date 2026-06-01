"""
Stage 4 — Refinement (deterministic, zero LLM calls)
Fixes common cross-layer inconsistencies purely in Python.
"""
import logging

logger = logging.getLogger(__name__)


def refine_schemas(schemas: dict) -> dict:
    """Deterministically fix cross-layer issues. No LLM calls."""
    try:
        if isinstance(schemas, dict) and 'repaired_schemas' in schemas:
            schemas = schemas['repaired_schemas']

        ui   = schemas.get('ui_config')  or {}
        api  = schemas.get('api_config') or {}
        db   = schemas.get('db_schema')  or {}
        auth = schemas.get('auth_config') or {}

        if not api.get('base_path'):
            api['base_path'] = '/api/v1'

        if not auth.get('strategy'):
            auth['strategy'] = 'jwt'
        if not auth.get('roles'):
            auth['roles'] = ['user', 'admin']
        if not auth.get('token_expiry'):
            auth['token_expiry'] = '24h'

        public_keywords = {'login', 'register', 'signup', 'health', 'status'}
        for ep in api.get('endpoints', []):
            if 'auth_required' not in ep:
                path = ep.get('path', '').lower()
                ep['auth_required'] = not any(k in path for k in public_keywords)

        for table in db.get('tables', []):
            cols = table.get('columns', [])
            if not any(c.get('name') in ('id',) for c in cols):
                cols.insert(0, {'name': 'id', 'type': 'UUID', 'primary_key': True, 'nullable': False})
            if not any(c.get('name') == 'created_at' for c in cols):
                cols.append({'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False, 'default': 'NOW()'})

        if not ui.get('pages'):
            ui['pages'] = [{'name': 'Home', 'path': '/', 'components': []}]

        schemas['ui_config']  = ui
        schemas['api_config'] = api
        schemas['db_schema']  = db
        schemas['auth_config'] = auth

        logger.info('Stage4 refinement done (deterministic)')
        return schemas

    except Exception as e:
        logger.warning(f'Stage4 error (returning as-is): {e}')
        return schemas


# __init__.py expects run()
def run(schemas: dict) -> dict:
    return refine_schemas(schemas)
