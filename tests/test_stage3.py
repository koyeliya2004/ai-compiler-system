"""
Unit tests for Stage 3 -- Schema Generation

Runs without a live LLM by patching chat_completion_json.
"""
import json
import pytest
from unittest.mock import patch, call

from pipeline.stage3_schema_generation import (
    generate_schemas,
    _validate_sub,
    _cross_layer_consistency,
    _sync_auth_roles,
    _sync_route_guards,
    _sync_db_tables,
    _to_snake,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_DESIGN = {
    "app_name": "TestCRM",
    "app_type": "CRM",
    "entities": [
        {
            "name": "Contact",
            "fields": [{"name": "id", "type": "uuid", "required": True}],
            "relations": []
        }
    ],
    "pages": [
        {"name": "Dashboard", "path": "/dashboard", "access": "authenticated", "components": []},
        {"name": "Admin",     "path": "/admin",     "access": "role_restricted", "allowed_roles": ["admin"], "components": []}
    ],
    "roles": [
        {"name": "admin", "description": "Admin", "capabilities": []},
        {"name": "user",  "description": "User",  "capabilities": []}
    ],
    "api_groups": [],
    "permission_matrix": {},
    "business_rules": [],
    "data_flows": [],
    "design_decisions": []
}

VALID_UI = {
    "theme": "light",
    "primary_color": "#7c6af7",
    "font_family": "Inter",
    "pages": [
        {
            "name": "Dashboard", "route": "/dashboard", "title": "Dashboard",
            "layout": "sidebar", "access": "authenticated",
            "components": [{"id": "kpi", "type": "Stats", "label": "KPIs", "props": {}}]
        }
    ],
    "global_components": ["Navbar"],
    "navigation": {
        "type": "sidebar",
        "items": [{"label": "Dashboard", "route": "/dashboard", "icon": "home"}]
    }
}

VALID_API = {
    "base_path": "/api/v1",
    "auth_strategy": "jwt",
    "versioning": "v1",
    "endpoints": [
        {
            "path": "/api/v1/contacts", "method": "GET",
            "description": "List contacts", "auth_required": True,
            "roles": ["admin", "user"],
            "response_schema": {"200": {"items": "array"}}
        },
        {
            "path": "/auth/login", "method": "POST",
            "description": "Login", "auth_required": False,
            "roles": [],
            "response_schema": {"200": {"token": "string"}}
        }
    ]
}

VALID_DB = {
    "dialect": "postgresql",
    "tables": [
        {
            "name": "contacts",
            "columns": [
                {"name": "id",         "type": "UUID",      "nullable": False, "primary_key": True},
                {"name": "created_at", "type": "TIMESTAMP", "nullable": False}
            ],
            "indexes": [],
            "foreign_keys": []
        }
    ],
    "migrations": [
        {"version": "001", "description": "Initial", "sql_up": "CREATE TABLE contacts (id UUID PRIMARY KEY);"}
    ]
}

VALID_AUTH = {
    "strategy": "jwt",
    "token_expiry": "24h",
    "refresh_token": True,
    "roles": [
        {"name": "admin", "inherits": [], "permissions": ["contact:read", "contact:write"]},
        {"name": "user",  "inherits": [], "permissions": ["contact:read"]}
    ],
    "route_guards": [
        {"route": "/admin", "allowed_roles": ["admin"], "redirect_to": "/login"}
    ],
    "password_policy": {
        "min_length": 8, "require_uppercase": True,
        "require_number": True, "require_special": True
    }
}

VALID_ALL = {
    "ui_config":   VALID_UI,
    "api_config":  VALID_API,
    "db_schema":   VALID_DB,
    "auth_config": VALID_AUTH,
}


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

def test_valid_ui_passes():
    assert _validate_sub('ui_config', VALID_UI) == []

def test_valid_api_passes():
    assert _validate_sub('api_config', VALID_API) == []

def test_valid_db_passes():
    assert _validate_sub('db_schema', VALID_DB) == []

def test_valid_auth_passes():
    assert _validate_sub('auth_config', VALID_AUTH) == []

def test_missing_theme_fails_ui():
    bad = {k: v for k, v in VALID_UI.items() if k != 'theme'}
    errors = _validate_sub('ui_config', bad)
    assert any('theme' in e['message'] for e in errors)

def test_missing_tables_fails_db():
    bad = {k: v for k, v in VALID_DB.items() if k != 'tables'}
    errors = _validate_sub('db_schema', bad)
    assert errors  # should have at least one error


# ---------------------------------------------------------------------------
# Cross-layer consistency tests
# ---------------------------------------------------------------------------

def test_sync_auth_roles_injects_missing():
    design = {**MINIMAL_DESIGN, 'roles': [
        {'name': 'admin'}, {'name': 'user'}, {'name': 'manager'}
    ]}
    schemas = {
        **VALID_ALL,
        'auth_config': {
            **VALID_AUTH,
            'roles': [{'name': 'admin', 'inherits': [], 'permissions': []}]
        }
    }
    result = _sync_auth_roles(design, schemas)
    names = [r['name'] for r in result['auth_config']['roles']]
    assert 'user' in names
    assert 'manager' in names


def test_sync_route_guards_adds_missing():
    schemas = {
        **VALID_ALL,
        'ui_config': {
            **VALID_UI,
            'pages': [
                {'name': 'Secret', 'route': '/secret', 'layout': 'sidebar',
                 'access': 'role_restricted', 'allowed_roles': ['admin'],
                 'components': []}
            ]
        },
        'auth_config': {**VALID_AUTH, 'route_guards': []}
    }
    result = _sync_route_guards(schemas)
    guard_routes = [g['route'] for g in result['auth_config']['route_guards']]
    assert '/secret' in guard_routes


def test_sync_db_tables_injects_stub():
    design = {**MINIMAL_DESIGN, 'entities': [
        {'name': 'Contact', 'fields': [], 'relations': []},
        {'name': 'NewEntity', 'fields': [], 'relations': []}
    ]}
    schemas = {**VALID_ALL, 'db_schema': {**VALID_DB, 'tables': [
        {'name': 'contacts', 'columns': [{'name': 'id', 'type': 'UUID', 'nullable': False}], 'indexes': [], 'foreign_keys': []}
    ]}}
    result = _sync_db_tables(design, schemas)
    table_names = [t['name'] for t in result['db_schema']['tables']]
    assert 'new_entity' in table_names


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------

def test_to_snake_pascal():
    assert _to_snake('UserProfile') == 'user_profile'

def test_to_snake_already_snake():
    assert _to_snake('contacts') == 'contacts'

def test_to_snake_title_space():
    assert _to_snake('Sales Deal') == 'sales_deal'


# ---------------------------------------------------------------------------
# Integration test (mocked LLM)
# ---------------------------------------------------------------------------

@patch('pipeline.stage3_schema_generation.chat_completion_json')
def test_generate_schemas_happy_path(mock_llm):
    """
    Mock LLM returns one of the 4 valid sub-schemas per call (in arbitrary order).
    generate_schemas should return all 4.
    """
    responses = [
        dict(VALID_UI),
        dict(VALID_API),
        dict(VALID_DB),
        dict(VALID_AUTH),
    ]
    mock_llm.side_effect = responses
    result = generate_schemas(MINIMAL_DESIGN)
    # All four keys must be present
    for key in ('ui_config', 'api_config', 'db_schema', 'auth_config'):
        assert key in result, f'Missing key: {key}'
