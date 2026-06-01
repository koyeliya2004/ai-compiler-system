"""
Unit tests for Stage 2 -- System Design Layer

Runs without a live LLM by patching chat_completion_json.
"""
import json
import pytest
from unittest.mock import patch

from pipeline.stage2_system_design import (
    design_system,
    _collect_errors,
    _cross_check,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_INTENT = {
    "app_name": "TestCRM",
    "app_type": "CRM",
    "description": "A simple CRM",
    "features": [],
    "roles": ["admin", "user"],
    "entities": ["Contact", "Deal"],
    "integrations": [],
    "assumptions": [],
    "clarifications_needed": []
}

VALID_DESIGN = {
    "app_name": "TestCRM",
    "app_type": "CRM",
    "entities": [
        {
            "name": "Contact",
            "description": "A CRM contact",
            "fields": [
                {"name": "id", "type": "uuid", "required": True},
                {"name": "name", "type": "string", "required": True},
                {"name": "email", "type": "string", "required": True, "unique": True}
            ],
            "relations": [{"type": "has_many", "target": "Deal"}]
        },
        {
            "name": "Deal",
            "description": "A sales deal",
            "fields": [
                {"name": "id", "type": "uuid", "required": True},
                {"name": "title", "type": "string", "required": True},
                {"name": "value", "type": "float", "required": False}
            ],
            "relations": [{"type": "belongs_to", "target": "Contact"}]
        }
    ],
    "pages": [
        {"name": "Dashboard", "path": "/dashboard", "access": "authenticated", "components": ["KPICard", "RecentDeals"]},
        {"name": "AdminPanel", "path": "/admin", "access": "role_restricted", "allowed_roles": ["admin"], "components": ["UserTable"]}
    ],
    "api_groups": [
        {
            "resource": "contacts",
            "base_path": "/api/v1/contacts",
            "endpoints": [
                {"method": "GET",  "path": "/",    "description": "List contacts", "auth_required": True, "roles": ["admin", "user"]},
                {"method": "POST", "path": "/",    "description": "Create contact", "auth_required": True, "roles": ["admin"]},
                {"method": "GET",  "path": "/:id", "description": "Get contact",    "auth_required": True, "roles": ["admin", "user"]}
            ]
        }
    ],
    "roles": [
        {"name": "admin", "description": "Full access",    "is_default": False, "capabilities": ["read","write","delete","export"]},
        {"name": "user",  "description": "Standard access", "is_default": True,  "capabilities": ["read","write"]}
    ],
    "permission_matrix": {
        "Contact": {
            "admin": ["create","read","update","delete","list","export"],
            "user":  ["create","read","update","list"]
        }
    },
    "business_rules": [
        {"id": "BR-001", "rule": "Only admin can delete contacts", "trigger": "DELETE /api/v1/contacts/:id", "action": "Return 403 for non-admin", "affects_roles": ["user"]}
    ],
    "data_flows": [
        {"name": "User Login", "steps": ["POST /auth/login", "Validate credentials", "Issue JWT", "Redirect to dashboard"]},
        {"name": "Create Contact", "steps": ["POST /api/v1/contacts", "Validate payload", "Persist to DB", "Return 201"]},
        {"name": "Admin Exports", "steps": ["GET /api/v1/contacts?export=true", "Check admin role", "Stream CSV"]}
    ],
    "design_decisions": [
        {"decision": "Use JWT for auth", "rationale": "Stateless, scales horizontally", "tradeoff": "Requires token refresh logic"},
        {"decision": "REST over GraphQL", "rationale": "Simpler tooling for CRUD-heavy CRM", "tradeoff": "Over-fetching on some pages"}
    ]
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_valid_design_passes_schema():
    errors = _collect_errors(VALID_DESIGN)
    assert errors == [], f"Expected no errors, got: {errors}"


def test_missing_required_key_fails_schema():
    bad = {k: v for k, v in VALID_DESIGN.items() if k != 'permission_matrix'}
    errors = _collect_errors(bad)
    assert any('permission_matrix' in e['message'] or 'permission_matrix' in e['path'] for e in errors)


def test_cross_check_injects_missing_role():
    intent = {**MINIMAL_INTENT, 'roles': ['admin', 'user', 'manager']}
    design = {**VALID_DESIGN, 'roles': [
        {'name': 'admin', 'description': 'Admin', 'is_default': False, 'capabilities': []},
        {'name': 'user',  'description': 'User',  'is_default': True,  'capabilities': []}
    ]}
    result = _cross_check(intent, design)
    role_names = [r['name'] for r in result['roles']]
    assert 'manager' in role_names, "cross_check should inject missing 'manager' role"


def test_cross_check_fixes_role_restricted_page():
    intent = MINIMAL_INTENT
    design = {
        **VALID_DESIGN,
        'pages': [
            {"name": "AdminPanel", "path": "/admin", "access": "role_restricted",
             "allowed_roles": ["nonexistent_role"], "components": []}
        ]
    }
    result = _cross_check(intent, design)
    page = result['pages'][0]
    known_roles = {r['name'] for r in result['roles']}
    assert all(r in known_roles for r in page['allowed_roles']), \
        "cross_check should replace invalid allowed_roles"


def test_cross_check_injects_missing_entity():
    intent = {**MINIMAL_INTENT, 'entities': ['Contact', 'Deal', 'Task']}
    result = _cross_check(intent, VALID_DESIGN)
    entity_names = [e['name'] for e in result['entities']]
    assert 'Task' in entity_names, "cross_check should inject stub entity 'Task'"


@patch('pipeline.stage2_system_design.chat_completion_json')
def test_design_system_happy_path(mock_llm):
    """Mock LLM returns valid design; design_system should return it unchanged."""
    mock_llm.return_value = dict(VALID_DESIGN)
    result = design_system(MINIMAL_INTENT)
    assert result['app_name'] == 'TestCRM'
    assert len(result['entities']) >= 2
    assert len(result['roles']) >= 2


@patch('pipeline.stage2_system_design.chat_completion_json')
def test_design_system_repairs_on_first_attempt(mock_llm):
    """First LLM call returns bad JSON; second call (repair) returns valid."""
    bad_design = {k: v for k, v in VALID_DESIGN.items() if k != 'business_rules'}
    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return dict(bad_design)
        return dict(VALID_DESIGN)

    mock_llm.side_effect = side_effect
    result = design_system(MINIMAL_INTENT)
    assert 'business_rules' in result
    assert call_count[0] == 2, "Should have called LLM twice (initial + 1 repair)"
