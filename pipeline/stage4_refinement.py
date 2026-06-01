"""
Stage 4 — Refinement (deterministic, zero LLM calls)
Fixes common cross-layer inconsistencies purely in Python.
"""
import logging

logger = logging.getLogger(__name__)


def refine_schemas(schemas: dict) -> dict:
    """Deterministically fix cross-layer issues. No LLM calls."""
    try:
        # Unwrap repaired_schemas wrapper if present
        if isinstance(schemas, dict) and 'repaired_schemas' in schemas:
            schemas = schemas['repaired_schemas']

        ui = schemas.get('ui_config') or {}
        api = schemas.get('api_config') or {}
        db = schemas.get('db_schema') or {}
        auth = schemas.get('auth_config') or {}

        # ── 1. Ensure base_path on API config
        if not api.get('base_path'):
            api['base_path'] = '/api/v1'

        # ── 2. Ensure auth config has minimum fields
        if not auth.get('strategy'):
            auth['strategy'] = 'jwt'
        if not auth.get('roles'):
            auth['roles'] = ['user', 'admin']
        if not auth.get('token_expiry'):
            auth['token_expiry'] = '24h'

        # ── 3. Add auth_required flag to endpoints that look protected
        endpoints = api.get('endpoints', [])
        public_keywords = {'login', 'register', 'signup', 'health', 'status'}
        for ep in endpoints:
            if 'auth_required' not in ep:
                path = ep.get('path', '').lower()
                ep['auth_required'] = not any(k in path for k in public_keywords)

        # ── 4. Ensure every DB table has an id column
        tables = db.get('tables', [])
        for table in tables:
            cols = table.get('columns', [])
            has_id = any(c.get('name') in ('id', table.get('name', '') + '_id') for c in cols)
            if not has_id:
                cols.insert(0, {
                    'name': 'id',
                    'type': 'UUID',
                    'primary_key': True,
                    'nullable': False
                })
            # Ensure created_at
            has_ts = any(c.get('name') == 'created_at' for c in cols)
            if not has_ts:
                cols.append({'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False, 'default': 'NOW()'})

        # ── 5. Ensure pages list is not empty
        pages = ui.get('pages', [])
        if not pages:
            ui['pages'] = [{'name': 'Home', 'path': '/', 'components': []}]

        schemas['ui_config'] = ui
        schemas['api_config'] = api
        schemas['db_schema'] = db
        schemas['auth_config'] = auth

        logger.info('Stage4 refinement done (deterministic)')
        return schemas

    except Exception as e:
        logger.warning(f'Stage4 refinement error (returning as-is): {e}')
        return schemas
