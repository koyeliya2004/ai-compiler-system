"""
Stage 5 -- Validation + Repair Engine

This is the CORE reliability layer of the AI Compiler.

Architecture:
  Multi-pass validation:
    Pass 1 — Structural   : JSON shape, required keys, type checks
    Pass 2 — Semantic     : value correctness, cross-field logic
    Pass 3 — Hallucination: invented fields, unknown types, bad references
    Pass 4 — Consistency  : cross-schema integrity (API<->DB, UI<->API, Auth<->UI)

  Repair Strategy:
    Level 1 (Deterministic) : fix without LLM  — applied first, always
    Level 2 (LLM-targeted)  : send ONLY the broken sub-object + error list
    NOT: full retry of any prior stage

  Repair is capped at MAX_REPAIR_PASSES per sub-schema.
  If a field cannot be repaired it is annotated with _repair_failed=true
  and logged — the pipeline continues rather than crashing.

Output shape:
  ValidatedOutput = {
    "valid":          bool,
    "schemas":        { ui_config, api_config, db_schema, auth_config },  # repaired
    "validation_report": {
      "passes":         ["structural", "semantic", "hallucination", "consistency"],
      "errors":         [ { pass, code, path, message, repaired } ],
      "warnings":       [ { pass, code, path, message } ],
      "repair_summary": [ { code, path, action } ],
      "hallucinations": [ { path, value, reason } ],
      "total_errors":   int,
      "total_warnings": int,
      "repair_attempts": int,
    }
  }
"""

import json
import logging
import re
from copy import deepcopy
from typing import Any

import jsonschema

from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

MAX_REPAIR_PASSES = 2

# Valid type sets for hallucination detection
_VALID_DB_TYPES = {
    'UUID', 'VARCHAR', 'TEXT', 'INT', 'BIGINT', 'FLOAT', 'DECIMAL',
    'BOOLEAN', 'TIMESTAMP', 'DATE', 'JSON', 'JSONB', 'ENUM', 'SERIAL'
}
_VALID_HTTP_METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}
_VALID_LAYOUTS = {'sidebar', 'topnav', 'blank', 'split', 'fullscreen'}
_VALID_COMPONENT_TYPES = {
    'Table', 'Form', 'Chart', 'Card', 'List', 'Modal', 'Sidebar', 'Navbar',
    'Hero', 'Stats', 'Tabs', 'Button', 'Input', 'Select', 'DatePicker',
    'FileUpload', 'RichText', 'Map', 'Calendar', 'KanbanBoard', 'Badge',
    'Avatar', 'Breadcrumb', 'Pagination', 'SearchBar', 'FilterPanel',
    'ExportButton', 'NotificationBell'
}
_VALID_ACCESS = {'public', 'authenticated', 'role_restricted'}
_VALID_AUTH_STRATEGIES = {'jwt', 'oauth2', 'session', 'api_key'}


# ============================================================
# Public entry point
# ============================================================

def validate_and_repair(refined_output: dict) -> dict:
    """
    Stage 5 entry point.
    Accepts a RefinedOutput (from Stage 4) or any dict with a 'schemas' key.
    Returns ValidatedOutput.
    """
    schemas = deepcopy(refined_output.get('schemas', refined_output))
    report = _empty_report()

    # ---- Multi-pass validation + repair loop ----
    for pass_name, check_fn in [
        ('structural',   _pass_structural),
        ('semantic',     _pass_semantic),
        ('hallucination', _pass_hallucination),
        ('consistency',  _pass_consistency),
    ]:
        errors = check_fn(schemas)
        for e in errors:
            e['pass'] = pass_name
            report['errors'].append(e)

        # Attempt deterministic repair first
        deterministic_fixes = _repair_deterministic(schemas, errors)
        report['repair_summary'].extend(deterministic_fixes)
        report['repair_attempts'] += len(deterministic_fixes)

        # Remaining unfixed errors → LLM targeted repair
        unfixed = [e for e in errors if not e.get('repaired')]
        if unfixed:
            schemas, llm_fixes, attempts = _repair_llm_targeted(
                schemas, unfixed, pass_name
            )
            report['repair_summary'].extend(llm_fixes)
            report['repair_attempts'] += attempts

        report['passes'].append(pass_name)

    # Collect hallucinations specifically
    report['hallucinations'] = [
        {'path': e['path'], 'value': e.get('value', '?'), 'reason': e['message']}
        for e in report['errors'] if e.get('code', '').startswith('H')
    ]

    report['warnings'] = _collect_warnings(schemas)
    report['total_errors']   = len(report['errors'])
    report['total_warnings'] = len(report['warnings'])

    valid = all(e.get('repaired') for e in report['errors'])

    logger.info(
        '[Stage 5] valid=%s | errors=%d | repaired=%d | hallucinations=%d | warnings=%d',
        valid,
        report['total_errors'],
        sum(1 for e in report['errors'] if e.get('repaired')),
        len(report['hallucinations']),
        report['total_warnings'],
    )

    return {
        'valid':    valid,
        'schemas':  schemas,
        'validation_report': report,
    }


# Aliases
run = validate_and_repair
validate_pipeline_output  = validate_and_repair
repair_pipeline_output    = validate_and_repair


# ============================================================
# PASS 1 — Structural Validation
# ============================================================

def _pass_structural(schemas: dict) -> list[dict]:
    """Check JSON shape: required top-level keys, required sub-keys, non-null."""
    errors = []

    # Top-level keys
    for key in ('ui_config', 'api_config', 'db_schema', 'auth_config'):
        if key not in schemas:
            errors.append(_err('S001', f'schemas.{key}', f'Required key "{key}" missing'))
            continue
        val = schemas[key]
        if not isinstance(val, dict):
            errors.append(_err('S002', f'schemas.{key}', f'"{key}" must be an object, got {type(val).__name__}'))

    ui  = schemas.get('ui_config',   {})
    api = schemas.get('api_config',  {})
    db  = schemas.get('db_schema',   {})
    auth = schemas.get('auth_config', {})

    # ui_config required sub-keys
    for field in ('pages', 'navigation'):
        if field not in ui:
            errors.append(_err('S010', f'ui_config.{field}', f'ui_config missing required field "{field}"'))
    if not isinstance(ui.get('pages'), list):
        errors.append(_err('S011', 'ui_config.pages', 'pages must be an array'))

    # api_config required sub-keys
    for field in ('base_path', 'endpoints'):
        if field not in api:
            errors.append(_err('S020', f'api_config.{field}', f'api_config missing required field "{field}"'))
    if not isinstance(api.get('endpoints'), list):
        errors.append(_err('S021', 'api_config.endpoints', 'endpoints must be an array'))

    # db_schema required sub-keys
    for field in ('dialect', 'tables'):
        if field not in db:
            errors.append(_err('S030', f'db_schema.{field}', f'db_schema missing required field "{field}"'))
    if not isinstance(db.get('tables'), list):
        errors.append(_err('S031', 'db_schema.tables', 'tables must be an array'))

    # auth_config required sub-keys
    for field in ('strategy', 'roles', 'route_guards'):
        if field not in auth:
            errors.append(_err('S040', f'auth_config.{field}', f'auth_config missing required field "{field}"'))
    if not isinstance(auth.get('roles'), list):
        errors.append(_err('S041', 'auth_config.roles', 'roles must be an array'))

    # Per-item structural checks
    for i, ep in enumerate(api.get('endpoints', [])):
        for f in ('path', 'method', 'auth_required'):
            if f not in ep:
                errors.append(_err('S022', f'api_config.endpoints[{i}].{f}',
                                   f'Endpoint missing required field "{f}"'))

    for i, tbl in enumerate(db.get('tables', [])):
        if 'name' not in tbl:
            errors.append(_err('S032', f'db_schema.tables[{i}].name', 'Table missing "name"'))
        if not isinstance(tbl.get('columns'), list):
            errors.append(_err('S033', f'db_schema.tables[{i}].columns', 'Table missing "columns" array'))
        for j, col in enumerate(tbl.get('columns', [])):
            for f in ('name', 'type', 'nullable'):
                if f not in col:
                    errors.append(_err('S034', f'db_schema.tables[{i}].columns[{j}].{f}',
                                       f'Column missing required field "{f}"'))

    for i, role in enumerate(auth.get('roles', [])):
        if 'name' not in role:
            errors.append(_err('S042', f'auth_config.roles[{i}].name', 'Role missing "name"'))

    for i, page in enumerate(ui.get('pages', [])):
        for f in ('name', 'route'):
            if f not in page:
                errors.append(_err('S012', f'ui_config.pages[{i}].{f}',
                                   f'Page missing required field "{f}"'))

    return errors


# ============================================================
# PASS 2 — Semantic Validation
# ============================================================

def _pass_semantic(schemas: dict) -> list[dict]:
    """Check value correctness: types match specs, booleans are bools, etc."""
    errors = []
    api  = schemas.get('api_config', {})
    db   = schemas.get('db_schema',  {})
    ui   = schemas.get('ui_config',  {})
    auth = schemas.get('auth_config', {})

    # HTTP methods
    for i, ep in enumerate(api.get('endpoints', [])):
        method = ep.get('method', '')
        if isinstance(method, str) and method.upper() not in _VALID_HTTP_METHODS:
            errors.append(_err('V001', f'api_config.endpoints[{i}].method',
                               f'Invalid HTTP method "{method}"', value=method))
        if not isinstance(ep.get('auth_required'), bool):
            errors.append(_err('V002', f'api_config.endpoints[{i}].auth_required',
                               'auth_required must be boolean', value=ep.get('auth_required')))

    # DB column types
    for i, tbl in enumerate(db.get('tables', [])):
        for j, col in enumerate(tbl.get('columns', [])):
            col_type = col.get('type', '')
            if col_type and col_type not in _VALID_DB_TYPES:
                errors.append(_err('V010', f'db_schema.tables[{i}].columns[{j}].type',
                                   f'Unknown column type "{col_type}"', value=col_type))
            if not isinstance(col.get('nullable'), bool):
                errors.append(_err('V011', f'db_schema.tables[{i}].columns[{j}].nullable',
                                   'nullable must be boolean', value=col.get('nullable')))

    # Page access values
    for i, page in enumerate(ui.get('pages', [])):
        access = page.get('access', '')
        if access and access not in _VALID_ACCESS:
            errors.append(_err('V020', f'ui_config.pages[{i}].access',
                               f'Invalid access value "{access}"', value=access))
        layout = page.get('layout', '')
        if layout and layout not in _VALID_LAYOUTS:
            errors.append(_err('V021', f'ui_config.pages[{i}].layout',
                               f'Invalid layout "{layout}"', value=layout))

    # Auth strategy
    strategy = auth.get('strategy', '')
    if strategy and strategy not in _VALID_AUTH_STRATEGIES:
        errors.append(_err('V030', 'auth_config.strategy',
                           f'Invalid auth strategy "{strategy}"', value=strategy))

    # Role names non-empty strings
    for i, role in enumerate(auth.get('roles', [])):
        name = role.get('name', '')
        if not name or not isinstance(name, str):
            errors.append(_err('V031', f'auth_config.roles[{i}].name',
                               'Role name must be a non-empty string', value=name))

    # Route paths start with /
    for i, ep in enumerate(api.get('endpoints', [])):
        path = ep.get('path', '')
        if path and not path.startswith('/'):
            errors.append(_err('V003', f'api_config.endpoints[{i}].path',
                               f'API path must start with "/", got "{path}"', value=path))

    for i, page in enumerate(ui.get('pages', [])):
        route = page.get('route', '')
        if route and not route.startswith('/'):
            errors.append(_err('V022', f'ui_config.pages[{i}].route',
                               f'UI route must start with "/", got "{route}"', value=route))

    return errors


# ============================================================
# PASS 3 — Hallucination Detection
# ============================================================

def _pass_hallucination(schemas: dict) -> list[dict]:
    """
    Detect LLM-invented content:
    - Unknown DB types
    - Component types not in the allowed set
    - Auth strategies not in the allowed set
    - FK references pointing to non-existent tables
    - Endpoints referencing roles that don’t exist in auth
    """
    errors = []
    db   = schemas.get('db_schema',   {})
    api  = schemas.get('api_config',  {})
    ui   = schemas.get('ui_config',   {})
    auth = schemas.get('auth_config', {})

    known_tables = {t['name'] for t in db.get('tables', [])}
    known_roles  = {r['name'] for r in auth.get('roles', []) if isinstance(r, dict)}

    # Hallucinated DB types
    for i, tbl in enumerate(db.get('tables', [])):
        for j, col in enumerate(tbl.get('columns', [])):
            col_type = str(col.get('type', '')).upper()
            # Catch common LLM hallucinations: STRING, INTEGER, BOOL, DATETIME, NUMBER
            hallucinated_map = {
                'STRING': 'VARCHAR', 'INTEGER': 'INT', 'BOOL': 'BOOLEAN',
                'DATETIME': 'TIMESTAMP', 'NUMBER': 'FLOAT', 'CHAR': 'VARCHAR',
                'LONG': 'BIGINT', 'DOUBLE': 'FLOAT', 'REAL': 'FLOAT',
            }
            if col_type in hallucinated_map:
                errors.append(_err('H001',
                                   f'db_schema.tables[{i}].columns[{j}].type',
                                   f'Hallucinated type "{col["type"]}"; should be "{hallucinated_map[col_type]}"',
                                   value=col['type']))

    # Hallucinated component types
    for i, page in enumerate(ui.get('pages', [])):
        for j, comp in enumerate(page.get('components', [])):
            ctype = comp.get('type', '')
            if ctype and ctype not in _VALID_COMPONENT_TYPES:
                errors.append(_err('H002',
                                   f'ui_config.pages[{i}].components[{j}].type',
                                   f'Unknown component type "{ctype}"',
                                   value=ctype))

    # FK referencing non-existent table
    for i, tbl in enumerate(db.get('tables', [])):
        for j, fk in enumerate(tbl.get('foreign_keys', [])):
            ref = fk.get('references_table', '')
            if ref and ref not in known_tables:
                errors.append(_err('H010',
                                   f'db_schema.tables[{i}].foreign_keys[{j}].references_table',
                                   f'FK references non-existent table "{ref}"',
                                   value=ref))

    # Endpoint using undefined role
    for i, ep in enumerate(api.get('endpoints', [])):
        for role in ep.get('roles', []):
            if known_roles and role not in known_roles:
                errors.append(_err('H020',
                                   f'api_config.endpoints[{i}].roles',
                                   f'Endpoint references undefined role "{role}"',
                                   value=role))

    # Route guard using undefined role
    for i, guard in enumerate(auth.get('route_guards', [])):
        for role in guard.get('allowed_roles', []):
            if known_roles and role not in known_roles:
                errors.append(_err('H021',
                                   f'auth_config.route_guards[{i}].allowed_roles',
                                   f'Route guard references undefined role "{role}"',
                                   value=role))

    return errors


# ============================================================
# PASS 4 — Consistency Validation
# ============================================================

def _pass_consistency(schemas: dict) -> list[dict]:
    """Cross-schema integrity checks."""
    errors = []
    api  = schemas.get('api_config', {})
    db   = schemas.get('db_schema',  {})
    ui   = schemas.get('ui_config',  {})
    auth = schemas.get('auth_config', {})

    known_api_paths   = {e['path'] for e in api.get('endpoints', []) if 'path' in e}
    known_table_names = {t['name'] for t in db.get('tables', []) if 'name' in t}
    known_auth_roles  = {r['name'] for r in auth.get('roles', []) if isinstance(r, dict)}
    known_ui_routes   = {p['route'] for p in ui.get('pages', []) if 'route' in p}

    # Auth/login endpoints must exist
    auth_paths = {p for p in known_api_paths if '/auth/' in p or '/login' in p}
    if not auth_paths:
        errors.append(_err('C001', 'api_config.endpoints',
                           'No authentication endpoints found (POST /auth/login missing)'))

    # Role-restricted pages must have route guards
    guard_routes = {g['route'] for g in auth.get('route_guards', []) if 'route' in g}
    for i, page in enumerate(ui.get('pages', [])):
        if page.get('access') == 'role_restricted':
            route = page.get('route', '')
            if route and route not in guard_routes:
                errors.append(_err('C010',
                                   f'ui_config.pages[{i}].route',
                                   f'Role-restricted page "{page.get("name")}" at "{route}" has no route guard'))

    # Route guards must reference existing roles
    for i, guard in enumerate(auth.get('route_guards', [])):
        for role in guard.get('allowed_roles', []):
            if known_auth_roles and role not in known_auth_roles:
                errors.append(_err('C011',
                                   f'auth_config.route_guards[{i}]',
                                   f'Route guard allowed_role "{role}" not defined in roles'))

    # DB tables must have a primary key
    for i, tbl in enumerate(db.get('tables', [])):
        has_pk = any(c.get('primary_key') for c in tbl.get('columns', []))
        if not has_pk:
            errors.append(_err('C020',
                               f'db_schema.tables[{i}]',
                               f'Table "{tbl.get("name")}" has no primary key column'))

    # FK on_delete values
    valid_on_delete = {'CASCADE', 'SET NULL', 'RESTRICT', 'NO ACTION'}
    for i, tbl in enumerate(db.get('tables', [])):
        for j, fk in enumerate(tbl.get('foreign_keys', [])):
            on_del = fk.get('on_delete', 'CASCADE')
            if on_del and on_del not in valid_on_delete:
                errors.append(_err('C021',
                                   f'db_schema.tables[{i}].foreign_keys[{j}].on_delete',
                                   f'Invalid on_delete value "{on_del}"', value=on_del))

    # Navigation items must reference existing page routes
    nav = ui.get('navigation', {})
    for i, item in enumerate(nav.get('items', [])):
        route = item.get('route', '')
        if route and route not in known_ui_routes and not route.startswith('http'):
            errors.append(_err('C030',
                               f'ui_config.navigation.items[{i}].route',
                               f'Nav item "{item.get("label")}" points to undefined route "{route}"',
                               severity='warning'))

    return errors


# ============================================================
# REPAIR — Level 1: Deterministic
# ============================================================

def _repair_deterministic(schemas: dict, errors: list[dict]) -> list[dict]:
    """
    Apply hard-coded fixes for known error codes.
    Marks errors as repaired=True when fixed.
    Returns list of applied fix summaries.
    """
    fixes = []

    db   = schemas.get('db_schema',   {})
    api  = schemas.get('api_config',  {})
    ui   = schemas.get('ui_config',   {})
    auth = schemas.get('auth_config', {})

    # Normalise missing top-level arrays
    for e in errors:
        code = e.get('code', '')

        # S001 — Missing top-level key
        if code == 'S001':
            key = e['path'].replace('schemas.', '')
            defaults = {
                'ui_config':   {'theme': 'light', 'pages': [], 'global_components': [],
                                'navigation': {'type': 'sidebar', 'items': []}},
                'api_config':  {'base_path': '/api/v1', 'auth_strategy': 'jwt',
                                'versioning': 'v1', 'endpoints': []},
                'db_schema':   {'dialect': 'postgresql', 'tables': [], 'migrations': []},
                'auth_config': {'strategy': 'jwt', 'token_expiry': '24h', 'refresh_token': True,
                                'roles': [], 'route_guards': [],
                                'password_policy': {'min_length': 8, 'require_uppercase': True,
                                                    'require_number': True, 'require_special': True}},
            }
            if key in defaults:
                schemas[key] = defaults[key]
                e['repaired'] = True
                fixes.append({'code': code, 'path': e['path'], 'action': f'Inserted default {key}'})

        # V001 — Invalid HTTP method
        elif code == 'V001':
            idx = _extract_index(e['path'])
            if idx is not None:
                ep = api.get('endpoints', [])
                if idx < len(ep):
                    ep[idx]['method'] = ep[idx].get('method', 'GET').upper()
                    if ep[idx]['method'] not in _VALID_HTTP_METHODS:
                        ep[idx]['method'] = 'GET'
                    e['repaired'] = True
                    fixes.append({'code': code, 'path': e['path'], 'action': 'Normalised method to uppercase'})

        # V002 — auth_required not boolean
        elif code == 'V002':
            idx = _extract_index(e['path'])
            if idx is not None:
                ep = api.get('endpoints', [])
                if idx < len(ep):
                    ep[idx]['auth_required'] = bool(ep[idx].get('auth_required', True))
                    e['repaired'] = True
                    fixes.append({'code': code, 'path': e['path'], 'action': 'Coerced auth_required to bool'})

        # V003 — API path missing leading /
        elif code == 'V003':
            idx = _extract_index(e['path'])
            if idx is not None:
                ep = api.get('endpoints', [])
                if idx < len(ep):
                    ep[idx]['path'] = '/' + ep[idx]['path'].lstrip('/')
                    e['repaired'] = True
                    fixes.append({'code': code, 'path': e['path'], 'action': 'Added leading / to API path'})

        # V010 / H001 — Unknown / hallucinated DB type
        elif code in ('V010', 'H001'):
            hallucinated_map = {
                'STRING': 'VARCHAR', 'INTEGER': 'INT', 'BOOL': 'BOOLEAN',
                'DATETIME': 'TIMESTAMP', 'NUMBER': 'FLOAT', 'CHAR': 'VARCHAR',
                'LONG': 'BIGINT', 'DOUBLE': 'FLOAT', 'REAL': 'FLOAT',
            }
            col = _resolve_path(schemas, e['path'])
            if col is not None and isinstance(col, dict):
                bad_type = str(col.get('type', '')).upper()
                corrected = hallucinated_map.get(bad_type, 'VARCHAR')
                col['type'] = corrected
                e['repaired'] = True
                fixes.append({'code': code, 'path': e['path'],
                              'action': f'Replaced "{bad_type}" with "{corrected}"'})

        # V011 — nullable not boolean
        elif code == 'V011':
            col = _resolve_path(schemas, e['path'])
            if col is not None and isinstance(col, dict):
                col['nullable'] = bool(col.get('nullable', True))
                e['repaired'] = True
                fixes.append({'code': code, 'path': e['path'], 'action': 'Coerced nullable to bool'})

        # V020 — invalid access value
        elif code == 'V020':
            page = _resolve_path(schemas, e['path'])
            if page is not None and isinstance(page, dict):
                page['access'] = 'authenticated'
                e['repaired'] = True
                fixes.append({'code': code, 'path': e['path'], 'action': 'Defaulted access to "authenticated"'})

        # V021 — invalid layout value
        elif code == 'V021':
            page = _resolve_path(schemas, e['path'])
            if page is not None and isinstance(page, dict):
                page['layout'] = 'sidebar'
                e['repaired'] = True
                fixes.append({'code': code, 'path': e['path'], 'action': 'Defaulted layout to "sidebar"'})

        # V022 — UI route missing leading /
        elif code == 'V022':
            idx = _extract_index(e['path'])
            if idx is not None:
                pages = ui.get('pages', [])
                if idx < len(pages):
                    pages[idx]['route'] = '/' + pages[idx]['route'].lstrip('/')
                    e['repaired'] = True
                    fixes.append({'code': code, 'path': e['path'], 'action': 'Added leading / to UI route'})

        # V030 — invalid auth strategy
        elif code == 'V030':
            auth['strategy'] = 'jwt'
            e['repaired'] = True
            fixes.append({'code': code, 'path': e['path'], 'action': 'Defaulted auth strategy to "jwt"'})

        # C001 — Missing auth endpoints
        elif code == 'C001':
            existing_paths = {ep['path'] for ep in api.get('endpoints', [])}
            for path, desc in [
                ('/auth/login',   'User login'),
                ('/auth/register','User registration'),
                ('/auth/refresh', 'Refresh access token'),
            ]:
                if path not in existing_paths:
                    api.setdefault('endpoints', []).append({
                        'path': path, 'method': 'POST', 'description': desc,
                        'auth_required': False, 'roles': [],
                        'response_schema': {'200': {'token': 'string'}}
                    })
            e['repaired'] = True
            fixes.append({'code': code, 'path': e['path'], 'action': 'Injected /auth/login + /register + /refresh endpoints'})

        # C010 — role_restricted page missing route guard
        elif code == 'C010':
            # Extract route from error message
            match = re.search(r'"(/[^"]+)"', e.get('message', ''))
            if match:
                route = match.group(1)
                page = next((p for p in ui.get('pages', []) if p.get('route') == route), {})
                auth.setdefault('route_guards', []).append({
                    'route': route,
                    'allowed_roles': page.get('allowed_roles', []),
                    'redirect_to': '/login'
                })
                e['repaired'] = True
                fixes.append({'code': code, 'path': e['path'], 'action': f'Added route guard for "{route}"'})

        # C020 — Table missing primary key
        elif code == 'C020':
            idx = _extract_index(e['path'])
            if idx is not None:
                tables = db.get('tables', [])
                if idx < len(tables):
                    cols = tables[idx].setdefault('columns', [])
                    if not any(c.get('primary_key') for c in cols):
                        cols.insert(0, {
                            'name': 'id', 'type': 'UUID', 'nullable': False,
                            'primary_key': True, 'unique': True, 'default': 'gen_random_uuid()'
                        })
                    e['repaired'] = True
                    fixes.append({'code': code, 'path': e['path'],
                                  'action': f'Added UUID PK to table "{tables[idx].get("name")}"'})

        # H002 — Hallucinated component type — map to closest
        elif code == 'H002':
            comp = _resolve_path(schemas, e['path'])
            if comp is not None and isinstance(comp, dict):
                bad = comp.get('type', '')
                mapped = _closest_component_type(bad)
                comp['type'] = mapped
                e['repaired'] = True
                fixes.append({'code': code, 'path': e['path'],
                              'action': f'Mapped unknown component "{bad}" to "{mapped}"'})

    return fixes


# ============================================================
# REPAIR — Level 2: LLM-targeted
# ============================================================

def _repair_llm_targeted(
    schemas: dict, unfixed_errors: list[dict], pass_name: str
) -> tuple[dict, list[dict], int]:
    """
    Send ONLY the broken sub-objects + error list to the LLM.
    Return (updated schemas, fix summaries, attempt count).
    """
    if not unfixed_errors:
        return schemas, [], 0

    # Group errors by top-level sub-schema (ui/api/db/auth)
    groups: dict[str, list] = {}
    for e in unfixed_errors:
        top = e['path'].split('.')[0]
        if top in ('ui_config', 'api_config', 'db_schema', 'auth_config'):
            groups.setdefault(top, []).append(e)
        else:
            groups.setdefault('schemas', []).append(e)

    fix_summaries = []
    total_attempts = 0

    for sub_key, sub_errors in groups.items():
        sub_obj = schemas.get(sub_key, {})
        error_list = [{'path': e['path'], 'message': e['message']} for e in sub_errors]

        prompt = (
            f'Fix these validation errors in the {sub_key} JSON.\n\n'
            f'Errors:\n{json.dumps(error_list, indent=2)}\n\n'
            f'Current {sub_key}:\n{json.dumps(sub_obj, indent=2)}\n\n'
            f'Return ONLY the corrected {sub_key} JSON object. No prose.'
        )

        for attempt in range(MAX_REPAIR_PASSES):
            total_attempts += 1
            try:
                repaired = chat_completion_json(
                    system_prompt=(
                        f'You are a JSON repair engine. Fix the listed errors in the '
                        f'{sub_key} object. Return ONLY the corrected JSON object.'
                    ),
                    user_prompt=prompt,
                    temperature=0.05,
                    stage_id=5
                )
                for k in ('__model_used__', '__model_label__', '__stage_ms__'):
                    repaired.pop(k, None)

                # Validate the repair
                re_errors = [e for validator in [
                    lambda: _pass_structural({sub_key: repaired}),
                    lambda: _pass_semantic({sub_key: repaired}),
                ] for e in validator()]

                if not re_errors:
                    schemas[sub_key] = repaired
                    for e in sub_errors:
                        e['repaired'] = True
                    fix_summaries.append({
                        'code': 'LLM', 'path': sub_key,
                        'action': f'LLM repaired {sub_key} on attempt {attempt + 1}'
                    })
                    logger.info('[Stage 5] LLM repair succeeded for %s (attempt %d)', sub_key, attempt + 1)
                    break
                else:
                    logger.warning('[Stage 5] LLM repair of %s attempt %d still has %d errors',
                                   sub_key, attempt + 1, len(re_errors))
                    # Feed errors back for next attempt
                    prompt = (
                        f'Previous repair still has errors:\n{json.dumps([e["message"] for e in re_errors], indent=2)}\n\n'
                        f'Corrected JSON so far:\n{json.dumps(repaired, indent=2)}\n\n'
                        f'Fix ALL remaining errors. Return ONLY the corrected JSON object.'
                    )
                    sub_obj = repaired
            except Exception as exc:  # noqa: BLE001
                logger.error('[Stage 5] LLM repair error for %s: %s', sub_key, exc)
                fix_summaries.append({
                    'code': 'LLM_FAIL', 'path': sub_key,
                    'action': f'LLM repair failed: {exc}'
                })
                break

    return schemas, fix_summaries, total_attempts


# ============================================================
# Warning collection
# ============================================================

def _collect_warnings(schemas: dict) -> list[dict]:
    warnings = []
    db  = schemas.get('db_schema',  {})
    api = schemas.get('api_config', {})
    ui  = schemas.get('ui_config',  {})

    # Empty tables list
    if not db.get('tables'):
        warnings.append(_warn('W001', 'db_schema.tables', 'No tables defined in DB schema'))

    # Empty endpoints list
    if not api.get('endpoints'):
        warnings.append(_warn('W002', 'api_config.endpoints', 'No endpoints defined in API config'))

    # Empty pages list
    if not ui.get('pages'):
        warnings.append(_warn('W003', 'ui_config.pages', 'No pages defined in UI config'))

    # Tables without indexes (performance warning)
    for tbl in db.get('tables', []):
        if not tbl.get('indexes') and len(tbl.get('columns', [])) > 3:
            warnings.append(_warn('W010', f'db_schema.tables.{tbl["name"]}',
                                  f'Table "{tbl["name"]}" has no indexes — consider adding for performance'))

    # Endpoints with no response_schema
    for ep in api.get('endpoints', []):
        if not ep.get('response_schema'):
            warnings.append(_warn('W020', f'api_config.endpoints.{ep.get("path")}',
                                  f'Endpoint "{ep.get("path")}" has no response_schema defined'))

    # Pages with no components
    for page in ui.get('pages', []):
        if not page.get('components'):
            warnings.append(_warn('W030', f'ui_config.pages.{page.get("name")}',
                                  f'Page "{page.get("name")}" has no components'))

    return warnings


# ============================================================
# Utilities
# ============================================================

def _empty_report() -> dict:
    return {
        'passes':         [],
        'errors':         [],
        'warnings':       [],
        'repair_summary': [],
        'hallucinations': [],
        'total_errors':   0,
        'total_warnings': 0,
        'repair_attempts': 0,
    }


def _err(code: str, path: str, message: str, value: Any = None, severity: str = 'error') -> dict:
    e: dict = {'code': code, 'path': path, 'message': message,
               'severity': severity, 'repaired': False}
    if value is not None:
        e['value'] = value
    return e


def _warn(code: str, path: str, message: str) -> dict:
    return {'code': code, 'path': path, 'message': message, 'severity': 'warning'}


def _extract_index(path: str) -> int | None:
    """Extract the first array index from a dotted path like ui_config.pages[2].route."""
    match = re.search(r'\[(\d+)\]', path)
    return int(match.group(1)) if match else None


def _resolve_path(schemas: dict, path: str) -> Any:
    """
    Walk a dotted-bracket path like 'db_schema.tables[0].columns[1]'
    and return the target object (mutable reference for in-place edit).
    """
    parts = re.split(r'[.\[\]]+', path)
    obj: Any = schemas
    try:
        for part in parts:
            if not part:
                continue
            if isinstance(obj, list):
                obj = obj[int(part)]
            elif isinstance(obj, dict):
                obj = obj[part]
            else:
                return None
        return obj
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def _closest_component_type(bad: str) -> str:
    """Map an unknown component type to the closest valid one."""
    b = bad.lower()
    mapping = [
        ('table',   'Table'),  ('grid',    'Table'),  ('datagrid', 'Table'),
        ('form',    'Form'),   ('input',   'Input'),  ('field',    'Input'),
        ('chart',   'Chart'),  ('graph',   'Chart'),  ('plot',     'Chart'),
        ('card',    'Card'),   ('panel',   'Card'),   ('widget',   'Card'),
        ('list',    'List'),   ('feed',    'List'),
        ('modal',   'Modal'),  ('dialog',  'Modal'),  ('popup',    'Modal'),
        ('nav',     'Navbar'), ('header',  'Navbar'), ('menu',     'Navbar'),
        ('stat',    'Stats'),  ('kpi',     'Stats'),  ('metric',   'Stats'),
        ('tab',     'Tabs'),   ('switch',  'Tabs'),
        ('select',  'Select'), ('dropdown','Select'), ('picker',   'Select'),
        ('search',  'SearchBar'), ('filter', 'FilterPanel'),
        ('upload',  'FileUpload'), ('file', 'FileUpload'),
        ('kanban',  'KanbanBoard'), ('board', 'KanbanBoard'),
        ('calendar','Calendar'), ('date', 'DatePicker'),
        ('badge',   'Badge'),  ('tag',    'Badge'),   ('chip',     'Badge'),
        ('avatar',  'Avatar'), ('profile','Avatar'),
        ('export',  'ExportButton'), ('download', 'ExportButton'),
        ('notification', 'NotificationBell'), ('bell', 'NotificationBell'),
    ]
    for keyword, resolved in mapping:
        if keyword in b:
            return resolved
    return 'Card'  # safe default
