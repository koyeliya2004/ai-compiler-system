"""
Unit tests for Stage 5 -- Validation + Repair Engine
Runs fully without a live LLM (deterministic repairs only).
"""
import pytest
from unittest.mock import patch
from copy import deepcopy

from pipeline.stage5_validation_repair import (
    validate_and_repair,
    _pass_structural,
    _pass_semantic,
    _pass_hallucination,
    _pass_consistency,
    _repair_deterministic,
    _extract_index,
    _resolve_path,
    _closest_component_type,
)


# ---------------------------------------------------------------------------
# Shared valid fixture
# ---------------------------------------------------------------------------

VALID_SCHEMAS = {
    'ui_config': {
        'theme': 'light',
        'pages': [
            {
                'name': 'Dashboard', 'route': '/dashboard',
                'layout': 'sidebar', 'access': 'authenticated',
                'components': [{'id': 'k1', 'type': 'Stats', 'props': {}}]
            },
            {
                'name': 'Admin', 'route': '/admin',
                'layout': 'sidebar', 'access': 'role_restricted',
                'allowed_roles': ['admin'],
                'components': []
            }
        ],
        'global_components': ['Navbar'],
        'navigation': {
            'type': 'sidebar',
            'items': [
                {'label': 'Dashboard', 'route': '/dashboard', 'icon': 'home'},
                {'label': 'Admin',     'route': '/admin',     'icon': 'shield'}
            ]
        }
    },
    'api_config': {
        'base_path': '/api/v1', 'auth_strategy': 'jwt', 'versioning': 'v1',
        'endpoints': [
            {'path': '/auth/login',    'method': 'POST', 'description': 'Login',
             'auth_required': False, 'roles': [], 'response_schema': {'200': {'token': 'string'}}},
            {'path': '/api/v1/contacts', 'method': 'GET', 'description': 'List contacts',
             'auth_required': True, 'roles': ['admin', 'user'], 'response_schema': {'200': {'items': 'array'}}},
        ]
    },
    'db_schema': {
        'dialect': 'postgresql',
        'tables': [
            {
                'name': 'contacts',
                'columns': [
                    {'name': 'id',   'type': 'UUID',   'nullable': False, 'primary_key': True},
                    {'name': 'name', 'type': 'VARCHAR', 'nullable': False, 'primary_key': False}
                ],
                'indexes': [{'name': 'idx_contacts_id', 'columns': ['id'], 'unique': True}],
                'foreign_keys': []
            }
        ],
        'migrations': [{'version': '001', 'description': 'Init', 'sql_up': 'CREATE TABLE contacts (id UUID PRIMARY KEY);'}]
    },
    'auth_config': {
        'strategy': 'jwt', 'token_expiry': '24h', 'refresh_token': True,
        'roles': [
            {'name': 'admin', 'inherits': [], 'permissions': ['contact:read', 'contact:write']},
            {'name': 'user',  'inherits': [], 'permissions': ['contact:read']}
        ],
        'route_guards': [
            {'route': '/admin', 'allowed_roles': ['admin'], 'redirect_to': '/login'}
        ],
        'password_policy': {
            'min_length': 8, 'require_uppercase': True,
            'require_number': True, 'require_special': True
        }
    }
}


# ---------------------------------------------------------------------------
# Pass 1: Structural
# ---------------------------------------------------------------------------

def test_structural_valid_schemas_no_errors():
    assert _pass_structural(VALID_SCHEMAS) == []

def test_structural_missing_top_key():
    schemas = {k: v for k, v in VALID_SCHEMAS.items() if k != 'db_schema'}
    errors = _pass_structural(schemas)
    assert any(e['code'] == 'S001' and 'db_schema' in e['path'] for e in errors)

def test_structural_missing_pages():
    s = deepcopy(VALID_SCHEMAS)
    del s['ui_config']['pages']
    errors = _pass_structural(s)
    assert any('pages' in e['path'] for e in errors)

def test_structural_missing_endpoint_method():
    s = deepcopy(VALID_SCHEMAS)
    del s['api_config']['endpoints'][0]['method']
    errors = _pass_structural(s)
    assert any('method' in e['path'] for e in errors)

def test_structural_missing_column_type():
    s = deepcopy(VALID_SCHEMAS)
    del s['db_schema']['tables'][0]['columns'][0]['type']
    errors = _pass_structural(s)
    assert any('type' in e['path'] for e in errors)


# ---------------------------------------------------------------------------
# Pass 2: Semantic
# ---------------------------------------------------------------------------

def test_semantic_valid_no_errors():
    assert _pass_semantic(VALID_SCHEMAS) == []

def test_semantic_bad_http_method():
    s = deepcopy(VALID_SCHEMAS)
    s['api_config']['endpoints'][0]['method'] = 'SEND'
    errors = _pass_semantic(s)
    assert any(e['code'] == 'V001' for e in errors)

def test_semantic_auth_required_not_bool():
    s = deepcopy(VALID_SCHEMAS)
    s['api_config']['endpoints'][0]['auth_required'] = 'yes'
    errors = _pass_semantic(s)
    assert any(e['code'] == 'V002' for e in errors)

def test_semantic_invalid_db_type():
    s = deepcopy(VALID_SCHEMAS)
    s['db_schema']['tables'][0]['columns'][0]['type'] = 'LONG_TEXT'
    errors = _pass_semantic(s)
    assert any(e['code'] == 'V010' for e in errors)

def test_semantic_invalid_access():
    s = deepcopy(VALID_SCHEMAS)
    s['ui_config']['pages'][0]['access'] = 'super_secret'
    errors = _pass_semantic(s)
    assert any(e['code'] == 'V020' for e in errors)

def test_semantic_route_missing_slash():
    s = deepcopy(VALID_SCHEMAS)
    s['ui_config']['pages'][0]['route'] = 'dashboard'
    errors = _pass_semantic(s)
    assert any(e['code'] == 'V022' for e in errors)


# ---------------------------------------------------------------------------
# Pass 3: Hallucination
# ---------------------------------------------------------------------------

def test_hallucination_string_type_detected():
    s = deepcopy(VALID_SCHEMAS)
    s['db_schema']['tables'][0]['columns'][0]['type'] = 'STRING'
    errors = _pass_hallucination(s)
    assert any(e['code'] == 'H001' for e in errors)

def test_hallucination_unknown_component():
    s = deepcopy(VALID_SCHEMAS)
    s['ui_config']['pages'][0]['components'][0]['type'] = 'DataGrid'
    errors = _pass_hallucination(s)
    assert any(e['code'] == 'H002' for e in errors)

def test_hallucination_fk_nonexistent_table():
    s = deepcopy(VALID_SCHEMAS)
    s['db_schema']['tables'][0]['foreign_keys'] = [{
        'column': 'user_id', 'references_table': 'ghost_table',
        'references_column': 'id', 'on_delete': 'CASCADE', 'on_update': 'CASCADE'
    }]
    errors = _pass_hallucination(s)
    assert any(e['code'] == 'H010' for e in errors)

def test_hallucination_endpoint_undefined_role():
    s = deepcopy(VALID_SCHEMAS)
    s['api_config']['endpoints'][0]['roles'] = ['superadmin']
    errors = _pass_hallucination(s)
    assert any(e['code'] == 'H020' for e in errors)


# ---------------------------------------------------------------------------
# Pass 4: Consistency
# ---------------------------------------------------------------------------

def test_consistency_valid_no_errors():
    errors = _pass_consistency(VALID_SCHEMAS)
    # only warnings allowed on a valid schema
    assert all(e.get('severity') == 'warning' for e in errors)

def test_consistency_missing_auth_endpoint():
    s = deepcopy(VALID_SCHEMAS)
    s['api_config']['endpoints'] = [e for e in s['api_config']['endpoints']
                                    if 'auth' not in e['path'] and 'login' not in e['path']]
    errors = _pass_consistency(s)
    assert any(e['code'] == 'C001' for e in errors)

def test_consistency_missing_route_guard():
    s = deepcopy(VALID_SCHEMAS)
    s['auth_config']['route_guards'] = []
    errors = _pass_consistency(s)
    assert any(e['code'] == 'C010' for e in errors)

def test_consistency_table_missing_pk():
    s = deepcopy(VALID_SCHEMAS)
    for col in s['db_schema']['tables'][0]['columns']:
        col['primary_key'] = False
    errors = _pass_consistency(s)
    assert any(e['code'] == 'C020' for e in errors)


# ---------------------------------------------------------------------------
# Deterministic repairs
# ---------------------------------------------------------------------------

def test_repair_hallucinated_type_string():
    s = deepcopy(VALID_SCHEMAS)
    s['db_schema']['tables'][0]['columns'][0]['type'] = 'STRING'
    errors = _pass_hallucination(s)
    fixes = _repair_deterministic(s, errors)
    assert s['db_schema']['tables'][0]['columns'][0]['type'] == 'VARCHAR'
    assert any('VARCHAR' in f['action'] for f in fixes)

def test_repair_auth_required_coercion():
    s = deepcopy(VALID_SCHEMAS)
    s['api_config']['endpoints'][0]['auth_required'] = 'yes'
    errors = _pass_semantic(s)
    _repair_deterministic(s, errors)
    assert s['api_config']['endpoints'][0]['auth_required'] is True

def test_repair_missing_route_guard():
    s = deepcopy(VALID_SCHEMAS)
    s['auth_config']['route_guards'] = []
    errors = _pass_consistency(s)
    _repair_deterministic(s, errors)
    guard_routes = [g['route'] for g in s['auth_config']['route_guards']]
    assert '/admin' in guard_routes

def test_repair_adds_pk_to_table():
    s = deepcopy(VALID_SCHEMAS)
    for col in s['db_schema']['tables'][0]['columns']:
        col['primary_key'] = False
    errors = _pass_consistency(s)
    _repair_deterministic(s, errors)
    assert any(c.get('primary_key') for c in s['db_schema']['tables'][0]['columns'])

def test_repair_injects_auth_endpoints():
    s = deepcopy(VALID_SCHEMAS)
    s['api_config']['endpoints'] = []
    errors = _pass_consistency(s)
    _repair_deterministic(s, errors)
    paths = [e['path'] for e in s['api_config']['endpoints']]
    assert '/auth/login' in paths

def test_repair_unknown_component_type():
    s = deepcopy(VALID_SCHEMAS)
    s['ui_config']['pages'][0]['components'][0]['type'] = 'DataGrid'
    errors = _pass_hallucination(s)
    _repair_deterministic(s, errors)
    assert s['ui_config']['pages'][0]['components'][0]['type'] == 'Table'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_extract_index_bracket():
    assert _extract_index('api_config.endpoints[3].method') == 3

def test_extract_index_none():
    assert _extract_index('api_config.base_path') is None

def test_resolve_path_dict():
    s = deepcopy(VALID_SCHEMAS)
    col = _resolve_path(s, 'db_schema.tables[0].columns[0]')
    assert col['name'] == 'id'

def test_resolve_path_bad():
    assert _resolve_path({}, 'nonexistent.path[99]') is None

def test_closest_component_datagrid():
    assert _closest_component_type('DataGrid') == 'Table'

def test_closest_component_kpi():
    assert _closest_component_type('KPIWidget') == 'Stats'

def test_closest_component_unknown():
    assert _closest_component_type('xyzabc') == 'Card'


# ---------------------------------------------------------------------------
# Full integration (no LLM — all errors are deterministically repairable)
# ---------------------------------------------------------------------------

def test_full_valid_schemas_pass():
    result = validate_and_repair({'schemas': VALID_SCHEMAS})
    assert result['valid'] is True
    assert result['validation_report']['total_errors'] == 0

def test_full_with_multiple_errors_repaired():
    s = deepcopy(VALID_SCHEMAS)
    # Inject several deterministically repairable errors
    s['db_schema']['tables'][0]['columns'][0]['type'] = 'STRING'    # H001
    s['api_config']['endpoints'][0]['auth_required'] = 'nope'       # V002
    s['ui_config']['pages'][0]['route'] = 'dashboard'              # V022
    s['auth_config']['route_guards'] = []                           # C010

    result = validate_and_repair({'schemas': s})
    assert result['schemas']['db_schema']['tables'][0]['columns'][0]['type'] == 'VARCHAR'
    assert result['schemas']['api_config']['endpoints'][0]['auth_required'] is True
    assert result['schemas']['ui_config']['pages'][0]['route'].startswith('/')
