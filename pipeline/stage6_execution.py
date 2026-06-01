"""
Stage 6: Execution Awareness
=============================
Verifies that the pipeline output is directly usable to generate a working app.

Checks:
- Has pages (routes)
- Has API endpoints
- Has DB tables
- Has auth roles
- All routes are guarded
- DB tables have primary keys
- API endpoints have HTTP methods
- Auth has at least one permission set
"""

import os
import json
import logging
from typing import Dict, Any

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=os.getenv('PIPELINE_LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)


def check_execution_readiness(final_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 6: Execution readiness gate.
    Verifies the output is directly usable by a runtime without manual fixes.
    """
    schemas = final_output.get('schemas', {})
    ui = schemas.get('ui_config', {})
    api = schemas.get('api_config', {})
    db = schemas.get('db_schema', {})
    auth = schemas.get('auth_config', {})

    pages = ui.get('pages', [])
    endpoints = api.get('endpoints', [])
    tables = db.get('tables', [])
    roles = auth.get('roles', [])
    guards = auth.get('route_guards', [])
    guard_routes = {g.get('route') for g in guards}

    checks = {}
    checks['has_pages'] = len(pages) > 0
    checks['has_api_endpoints'] = len(endpoints) > 0
    checks['has_db_tables'] = len(tables) > 0
    checks['has_auth_roles'] = len(roles) > 0
    checks['all_routes_guarded'] = all(p.get('route') in guard_routes for p in pages) if pages else False
    checks['db_tables_have_primary_keys'] = all(
        any(col.get('primary_key') for col in t.get('columns', []))
        for t in tables
    ) if tables else False
    checks['api_endpoints_have_methods'] = all(
        ep.get('method') in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
        for ep in endpoints
    ) if endpoints else False
    checks['auth_has_permissions'] = bool(
        auth.get('permissions') and any(v for v in auth['permissions'].values())
    ) or bool(any(r.get('permissions') for r in roles))

    is_executable = all(checks.values())
    issues = [k for k, v in checks.items() if not v]

    route_list = [p.get('route') for p in pages]
    endpoint_list = [f"{ep.get('method')} {ep.get('path')}" for ep in endpoints]
    table_list = [t.get('name') for t in tables]
    role_list = [r.get('name') for r in roles]

    preview = {
        'app_name': final_output.get('app_name', 'Generated App'),
        'routes': route_list,
        'api_endpoints': endpoint_list,
        'db_tables': table_list,
        'auth_roles': role_list,
        'boot_log': [
            f"[BOOT] Starting {final_output.get('app_name', 'Generated App')} v{final_output.get('pipeline_version', '0.1.0')}",
            f"[BOOT] Loaded {len(route_list)} route(s): {', '.join(route_list[:5])}",
            f"[BOOT] Registered {len(endpoint_list)} API endpoint(s)",
            f"[BOOT] Connected to DB with {len(table_list)} table(s): {', '.join(table_list[:5])}",
            f"[BOOT] Auth: JWT, roles={role_list}",
            f"[BOOT] Status: {'READY ✅' if is_executable else 'NOT READY ❌ — ' + str(issues)}"
        ]
    }

    if is_executable:
        logger.info(f'[Stage 6] ✅ EXECUTION READY — {len(route_list)} routes, {len(endpoint_list)} endpoints, {len(table_list)} tables')
    else:
        logger.error(f'[Stage 6] ❌ NOT executable. Failed checks: {issues}')

    return {
        'is_executable': is_executable,
        'checks': checks,
        'issues': issues,
        'preview': preview
    }


if __name__ == '__main__':
    print('[Stage 6] Import check_execution_readiness(final_output) from this module.')
