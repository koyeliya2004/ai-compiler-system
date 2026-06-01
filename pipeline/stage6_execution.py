"""
Stage 6 — Execution Readiness Gate
"""
import logging

logger = logging.getLogger(__name__)

READINESS_CHECKS = [
    ('has_ui_pages',      lambda o: len(o.get('schemas',{}).get('ui_config',{}).get('pages',[])) > 0),
    ('has_api_endpoints', lambda o: len(o.get('schemas',{}).get('api_config',{}).get('endpoints',[])) > 0),
    ('has_db_tables',     lambda o: len(o.get('schemas',{}).get('db_schema',{}).get('tables',[])) > 0),
    ('has_auth_strategy', lambda o: bool(o.get('schemas',{}).get('auth_config',{}).get('strategy'))),
    ('has_auth_roles',    lambda o: len(o.get('schemas',{}).get('auth_config',{}).get('roles',[])) > 0),
    ('has_blueprint',     lambda o: bool(o.get('blueprint'))),
    ('has_app_name',      lambda o: bool(o.get('app_name'))),
]


def check_execution_readiness(output: dict) -> dict:
    passed, failed, issues = [], [], []
    for name, fn in READINESS_CHECKS:
        try:
            ok = fn(output)
        except Exception:
            ok = False
        (passed if ok else failed).append(name)
        if not ok:
            issues.append(f'Failed: {name}')

    is_executable = len(failed) == 0
    score = round(len(passed) / len(READINESS_CHECKS) * 100)
    schemas = output.get('schemas', {})

    boot_log = [
        f"\u2705 App: {output.get('app_name', 'Unknown')}",
        f"\u2705 Auth: {schemas.get('auth_config', {}).get('strategy', 'none')}",
        f"\u2705 Roles: {', '.join(schemas.get('auth_config', {}).get('roles', []))}",
        f"\u2705 Pages: {len(schemas.get('ui_config', {}).get('pages', []))}",
        f"\u2705 Endpoints: {len(schemas.get('api_config', {}).get('endpoints', []))}",
        f"\u2705 DB Tables: {len(schemas.get('db_schema', {}).get('tables', []))}",
        f"{'\u2705' if is_executable else '\u274c'} Gate: {'PASS' if is_executable else 'FAIL'}",
    ]

    logger.info(f'[Stage6] executable={is_executable} score={score}% failed={failed}')
    return {
        'is_executable': is_executable,
        'readiness_score': score,
        'checks_passed': passed,
        'checks_failed': failed,
        'issues': issues,
        'preview': {'boot_log': boot_log}
    }
