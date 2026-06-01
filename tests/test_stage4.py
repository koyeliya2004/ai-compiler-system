"""
Unit tests for Stage 4 -- Refinement Layer
Runs without a live LLM.
"""
import pytest
from pipeline.stage4_refinement import (
    refine,
    _check_auth_role_completeness,
    _check_role_restricted_guards,
    _check_fk_table_existence,
    _check_enum_values_defined,
    _check_required_nullable,
    _check_m2m_join_tables,
    _check_premium_gating_field,
    _check_payment_table,
    _check_orphan_fk_columns,
    _infer_table_from_path,
    _to_snake,
    _score,
    _Context,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

MINIMAL_INTENT = {
    'app_type': 'CRM',
    'features': ['contacts', 'dashboard'],
    'roles': ['admin', 'user'],
}

MINIMAL_DESIGN = {
    'app_name': 'TestCRM',
    'entities': [{'name': 'Contact', 'fields': [], 'relations': []}],
    'pages': [{'name': 'Dashboard', 'path': '/dashboard', 'access': 'authenticated', 'components': []}],
    'roles': [{'name': 'admin'}, {'name': 'user'}],
    'business_rules': [],
    'permission_matrix': {},
    'api_groups': [],
    'data_flows': [],
    'design_decisions': [],
}

MINIMAL_SCHEMAS = {
    'ui_config': {
        'theme': 'light', 'pages': [], 'global_components': [],
        'navigation': {'type': 'sidebar', 'items': []}
    },
    'api_config': {
        'base_path': '/api/v1', 'auth_strategy': 'jwt',
        'versioning': 'v1', 'endpoints': []
    },
    'db_schema': {
        'dialect': 'postgresql',
        'tables': [
            {
                'name': 'contacts',
                'columns': [
                    {'name': 'id', 'type': 'UUID', 'nullable': False, 'primary_key': True},
                    {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False}
                ],
                'indexes': [], 'foreign_keys': []
            }
        ],
        'migrations': []
    },
    'auth_config': {
        'strategy': 'jwt', 'token_expiry': '24h', 'refresh_token': True,
        'roles': [{'name': 'admin', 'inherits': [], 'permissions': []}],
        'route_guards': [],
        'password_policy': {
            'min_length': 8, 'require_uppercase': True,
            'require_number': True, 'require_special': True
        }
    }
}


def _ctx(**overrides):
    import copy
    report = {'conflicts_found': [], 'conflicts_resolved': [], 'assumptions_made': [], 'warnings': [], 'unresolvable': []}
    design  = copy.deepcopy(overrides.get('design', MINIMAL_DESIGN))
    schemas = copy.deepcopy(overrides.get('schemas', MINIMAL_SCHEMAS))
    intent  = copy.deepcopy(overrides.get('intent', MINIMAL_INTENT))
    return _Context(intent, design, schemas, report)


# ---------------------------------------------------------------------------
# Rule C: Auth role completeness
# ---------------------------------------------------------------------------

def test_auth_role_completeness_injects_missing():
    ctx = _ctx()
    # 'user' is in design but not in auth_config
    _check_auth_role_completeness(ctx)
    auth_names = [r['name'] for r in ctx.schemas['auth_config']['roles']]
    assert 'user' in auth_names
    assert any('user' in r['fix'] for r in ctx.report['conflicts_resolved'])


# ---------------------------------------------------------------------------
# Rule J: Route guard coverage
# ---------------------------------------------------------------------------

def test_role_restricted_guard_added():
    import copy
    schemas = copy.deepcopy(MINIMAL_SCHEMAS)
    schemas['ui_config']['pages'] = [{
        'name': 'Admin', 'route': '/admin', 'layout': 'sidebar',
        'access': 'role_restricted', 'allowed_roles': ['admin'], 'components': []
    }]
    ctx = _ctx(schemas=schemas)
    _check_role_restricted_guards(ctx)
    guard_routes = [g['route'] for g in ctx.schemas['auth_config']['route_guards']]
    assert '/admin' in guard_routes


# ---------------------------------------------------------------------------
# Rule F: FK table existence
# ---------------------------------------------------------------------------

def test_missing_fk_table_stubbed():
    import copy
    schemas = copy.deepcopy(MINIMAL_SCHEMAS)
    schemas['db_schema']['tables'][0]['foreign_keys'] = [{
        'column': 'user_id', 'references_table': 'users',
        'references_column': 'id', 'on_delete': 'CASCADE', 'on_update': 'CASCADE'
    }]
    ctx = _ctx(schemas=schemas)
    _check_fk_table_existence(ctx)
    table_names = [t['name'] for t in ctx.schemas['db_schema']['tables']]
    assert 'users' in table_names
    assert any('users' in r['fix'] for r in ctx.report['conflicts_resolved'])


# ---------------------------------------------------------------------------
# Rule G: Enum values
# ---------------------------------------------------------------------------

def test_enum_no_values_gets_defaults():
    import copy
    schemas = copy.deepcopy(MINIMAL_SCHEMAS)
    schemas['db_schema']['tables'][0]['columns'].append(
        {'name': 'status', 'type': 'ENUM', 'nullable': False, 'enum_values': []}
    )
    ctx = _ctx(schemas=schemas)
    _check_enum_values_defined(ctx)
    col = next(c for t in ctx.schemas['db_schema']['tables']
               for c in t['columns'] if c['name'] == 'status')
    assert col['enum_values'] == ['active', 'inactive']


# ---------------------------------------------------------------------------
# Rule H: PK nullable
# ---------------------------------------------------------------------------

def test_pk_nullable_fixed():
    import copy
    schemas = copy.deepcopy(MINIMAL_SCHEMAS)
    schemas['db_schema']['tables'][0]['columns'][0]['nullable'] = True
    ctx = _ctx(schemas=schemas)
    _check_required_nullable(ctx)
    pk_col = ctx.schemas['db_schema']['tables'][0]['columns'][0]
    assert pk_col['nullable'] is False


# ---------------------------------------------------------------------------
# Rule K: M2M join table
# ---------------------------------------------------------------------------

def test_m2m_creates_join_table():
    import copy
    design = copy.deepcopy(MINIMAL_DESIGN)
    design['entities'] = [
        {'name': 'User', 'fields': [], 'relations': [{'type': 'many_to_many', 'target': 'Tag'}]},
        {'name': 'Tag',  'fields': [], 'relations': []}
    ]
    ctx = _ctx(design=design)
    _check_m2m_join_tables(ctx)
    table_names = [t['name'] for t in ctx.schemas['db_schema']['tables']]
    assert 'user_tag' in table_names or 'tag_user' in table_names


# ---------------------------------------------------------------------------
# Rule L: Premium gating
# ---------------------------------------------------------------------------

def test_premium_gating_creates_subscriptions_table():
    import copy
    design = copy.deepcopy(MINIMAL_DESIGN)
    design['business_rules'] = ['Premium plan users can access analytics']
    ctx = _ctx(design=design)
    _check_premium_gating_field(ctx)
    table_names = [t['name'] for t in ctx.schemas['db_schema']['tables']]
    assert 'subscriptions' in table_names


# ---------------------------------------------------------------------------
# Rule N: Payments table
# ---------------------------------------------------------------------------

def test_payment_intent_creates_payments_table():
    intent = {**MINIMAL_INTENT, 'features': ['payments', 'stripe checkout']}
    ctx = _ctx(intent=intent)
    _check_payment_table(ctx)
    table_names = [t['name'] for t in ctx.schemas['db_schema']['tables']]
    assert 'payments' in table_names


# ---------------------------------------------------------------------------
# Rule O: Orphan FK columns
# ---------------------------------------------------------------------------

def test_orphan_fk_column_declared():
    import copy
    schemas = copy.deepcopy(MINIMAL_SCHEMAS)
    # Add a second table
    schemas['db_schema']['tables'].append({
        'name': 'notes',
        'columns': [
            {'name': 'id',          'type': 'UUID',    'nullable': False, 'primary_key': True},
            {'name': 'contact_id',  'type': 'UUID',    'nullable': True,  'primary_key': False}
        ],
        'indexes': [], 'foreign_keys': []
    })
    ctx = _ctx(schemas=schemas)
    _check_orphan_fk_columns(ctx)
    notes = next(t for t in ctx.schemas['db_schema']['tables'] if t['name'] == 'notes')
    fk_cols = [fk['column'] for fk in notes.get('foreign_keys', [])]
    assert 'contact_id' in fk_cols


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_score_perfect():
    report = {'conflicts_found': [], 'conflicts_resolved': [], 'unresolvable': []}
    assert _score(report) == 100

def test_score_with_errors():
    report = {
        'conflicts_found': [{'severity': 'error'}, {'severity': 'warning'}],
        'conflicts_resolved': [{'rule': 'A', 'fix': 'x'}],
        'unresolvable': []
    }
    # 100 - 5 (error) - 2 (warning) + 2 (1 resolved) = 95
    assert _score(report) == 95

def test_score_floor_zero():
    report = {
        'conflicts_found': [{'severity': 'error'}] * 30,
        'conflicts_resolved': [],
        'unresolvable': []
    }
    assert _score(report) == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_infer_table_from_path():
    assert _infer_table_from_path('/api/v1/contacts') == 'contacts'
    assert _infer_table_from_path('/api/v1/users/profile') == 'profile'
    assert _infer_table_from_path('/auth/login') == 'login'

def test_to_snake():
    assert _to_snake('UserProfile') == 'user_profile'
    assert _to_snake('CRMContact')  == 'crm_contact'


# ---------------------------------------------------------------------------
# Integration smoke test (no LLM)
# ---------------------------------------------------------------------------

def test_refine_returns_all_keys():
    result = refine(MINIMAL_INTENT, MINIMAL_DESIGN, MINIMAL_SCHEMAS)
    assert 'intent'    in result
    assert 'design'    in result
    assert 'schemas'   in result
    assert 'refinement_report' in result
    rr = result['refinement_report']
    assert 'consistency_score' in rr
    assert isinstance(rr['consistency_score'], int)
    assert 0 <= rr['consistency_score'] <= 100
