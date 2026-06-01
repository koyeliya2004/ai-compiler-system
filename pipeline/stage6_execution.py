"""
Stage 6 — Execution Awareness
Verifies the output is directly usable to generate a working application.
Gates on readiness before marking is_executable=True.
"""
import logging

logger = logging.getLogger(__name__)

READINESS_CHECKS = [
    ("has_ui_pages",       lambda o: len(o.get("schemas",{}).get("ui_config",{}).get("pages",[])) > 0),
    ("has_api_endpoints",  lambda o: len(o.get("schemas",{}).get("api_config",{}).get("endpoints",[])) > 0),
    ("has_db_tables",      lambda o: len(o.get("schemas",{}).get("db_schema",{}).get("tables",[])) > 0),
    ("has_auth_strategy",  lambda o: bool(o.get("schemas",{}).get("auth_config",{}).get("strategy"))),
    ("has_auth_roles",     lambda o: len(o.get("schemas",{}).get("auth_config",{}).get("roles",[])) > 0),
    ("has_blueprint",      lambda o: bool(o.get("blueprint"))),
    ("has_app_name",       lambda o: bool(o.get("app_name"))),
]


def check_execution_readiness(output: dict) -> dict:
    """Stage 6: Gate on execution readiness."""
    passed = []
    failed = []
    issues = []

    for check_name, check_fn in READINESS_CHECKS:
        try:
            ok = check_fn(output)
        except Exception:
            ok = False
        if ok:
            passed.append(check_name)
        else:
            failed.append(check_name)
            issues.append(f"Readiness check failed: {check_name}")

    is_executable = len(failed) == 0
    score = round(len(passed) / len(READINESS_CHECKS) * 100)

    schemas = output.get("schemas", {})
    boot_log = [
        f"✅ App: {output.get('app_name','Unknown')}",
        f"✅ Auth strategy: {schemas.get('auth_config',{}).get('strategy','none')}",
        f"✅ Roles: {', '.join(schemas.get('auth_config',{}).get('roles',[]))}",
        f"✅ Pages: {len(schemas.get('ui_config',{}).get('pages',[]))}",
        f"✅ API endpoints: {len(schemas.get('api_config',{}).get('endpoints',[]))}",
        f"✅ DB tables: {len(schemas.get('db_schema',{}).get('tables',[]))}",
        f"{'✅' if is_executable else '❌'} Execution gate: {'PASS' if is_executable else 'FAIL'}",
    ]

    logger.info(f"[Stage6] is_executable={is_executable} score={score}% failed={failed}")
    return {
        "is_executable": is_executable,
        "readiness_score": score,
        "checks_passed": passed,
        "checks_failed": failed,
        "issues": issues,
        "preview": {"boot_log": boot_log}
    }
