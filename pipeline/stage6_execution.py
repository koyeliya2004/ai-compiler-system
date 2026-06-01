"""
Stage 6 — Execution Readiness (deterministic, zero LLM calls)
"""
import logging

logger = logging.getLogger(__name__)


def check_execution_readiness(output: dict) -> dict:
    schemas   = output.get('schemas') or {}
    if isinstance(schemas, dict) and 'repaired_schemas' in schemas:
        schemas = schemas['repaired_schemas']

    app_name  = output.get('app_name', 'App')
    ui        = schemas.get('ui_config')  or {}
    api       = schemas.get('api_config') or {}
    db        = schemas.get('db_schema')  or {}
    auth      = schemas.get('auth_config') or {}

    pages     = ui.get('pages', [])
    endpoints = api.get('endpoints', [])
    tables    = db.get('tables', [])
    roles     = auth.get('roles', [])
    strategy  = auth.get('strategy', 'unknown')
    base_path = api.get('base_path', '/api/v1')

    issues, boot_log = [], []

    boot_log.append(f'[BOOT] Starting {app_name}...')
    boot_log.append(f'[DB]   Connecting to database...')

    if tables:
        for t in tables[:5]:
            boot_log.append(f'[DB]   Migrating table: {t.get("name", "unknown")}')
        boot_log.append(f'[DB]   {len(tables)} table(s) migrated ✓')
    else:
        issues.append('No database tables defined')
        boot_log.append('[DB]   ⚠ No tables found')

    boot_log.append(f'[AUTH] Strategy: {strategy}')
    if roles:
        boot_log.append(f'[AUTH] Roles: {", ".join(str(r) for r in roles[:6])} ✓')
    else:
        issues.append('No auth roles defined')

    boot_log.append(f'[API]  Registering routes on {base_path}...')
    if endpoints:
        for ep in endpoints[:6]:
            method    = ep.get('method', 'GET')
            path      = ep.get('path', '/?')
            auth_flag = ' [auth]' if ep.get('auth_required') else ''
            boot_log.append(f'[API]  {method:<6} {path}{auth_flag}')
        if len(endpoints) > 6:
            boot_log.append(f'[API]  ... and {len(endpoints) - 6} more')
        boot_log.append(f'[API]  {len(endpoints)} endpoint(s) registered ✓')
    else:
        issues.append('No API endpoints defined')
        boot_log.append('[API]  ⚠ No endpoints found')

    boot_log.append(f'[UI]   Loading {len(pages)} page(s)...')
    if not pages:
        issues.append('No UI pages defined')

    is_executable = len(issues) == 0
    boot_log.append(f'[BOOT] {app_name} is ready ✓' if is_executable else f'[BOOT] ⚠ {len(issues)} issue(s) found')

    return {'is_executable': is_executable, 'issues': issues, 'preview': {'boot_log': boot_log}}


# __init__.py expects run()
def run(output: dict) -> dict:
    return check_execution_readiness(output)
