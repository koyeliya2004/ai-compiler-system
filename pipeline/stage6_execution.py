"""
Stage 6 — Execution Readiness Gate
"""
import os
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
    ('has_database_url',  lambda o: bool(os.getenv('DATABASE_URL', '').strip())),
]

TICK = '\u2705'
CROSS = '\u274c'


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

    gate_icon = TICK if is_executable else CROSS
    gate_word = 'PASS' if is_executable else 'FAIL'
    db_url_set = bool(os.getenv('DATABASE_URL', '').strip())
    db_icon = TICK if db_url_set else CROSS

    boot_log = [
        f"{TICK} App: {output.get('app_name', 'Unknown')}",
        f"{TICK} Auth: {schemas.get('auth_config', {}).get('strategy', 'none')}",
        f"{TICK} Roles: {', '.join(schemas.get('auth_config', {}).get('roles', []))}",
        f"{TICK} Pages: {len(schemas.get('ui_config', {}).get('pages', []))}",
        f"{TICK} Endpoints: {len(schemas.get('api_config', {}).get('endpoints', []))}",
        f"{TICK} DB Tables: {len(schemas.get('db_schema', {}).get('tables', []))}",
        f"{db_icon} DATABASE_URL: {'set' if db_url_set else 'NOT SET — add in Render Environment tab'}",
        f"{gate_icon} Gate: {gate_word}",
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
