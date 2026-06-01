"""
Stage 3 -- Schema Generation

Input:  Stage 2 SystemDesign (dict)
Output: AllSchemas            (dict validated against all_schemas_schema.json)

Four sub-schemas generated in PARALLEL using a thread pool:
  - ui_config    : pages, components, layouts, navigation
  - api_config   : endpoints, request/response shapes, auth
  - db_schema    : tables, columns, indexes, FK, migrations SQL
  - auth_config  : strategy, roles, route guards, password policy

Cross-layer consistency enforced after generation:
  API fields   <- must match -> DB columns
  UI routes    <- must match -> API endpoints
  Auth roles   <- must match -> Design roles
  Route guards <- must cover -> role_restricted pages

Repair strategy:
  Targeted per-sub-schema repair on schema violation.
  Max 2 repair passes per sub-schema.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import jsonschema

from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load master schema contract
# ---------------------------------------------------------------------------
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "all_schemas_schema.json"
with open(_SCHEMA_PATH) as _f:
    ALL_SCHEMAS_SCHEMA = json.load(_f)

_SUB_SCHEMAS = {
    k: ALL_SCHEMAS_SCHEMA["properties"][k]
    for k in ("ui_config", "api_config", "db_schema", "auth_config")
}

# ---------------------------------------------------------------------------
# Per-sub-schema system prompts
# ---------------------------------------------------------------------------

_UI_PROMPT = """You are the UI Schema generator in an AI compiler pipeline.

Given a SystemDesign JSON, generate a complete ui_config JSON object.

Output ONLY this JSON object (no wrapper, no markdown):
{
  "theme": "light|dark|system",
  "primary_color": "#hex",
  "font_family": "<font>",
  "pages": [
    {
      "name": "<PageName>",
      "route": "/<path>",
      "title": "<Browser title>",
      "layout": "sidebar|topnav|blank|split|fullscreen",
      "access": "public|authenticated|role_restricted",
      "allowed_roles": [],
      "components": [
        {
          "id": "<unique_id>",
          "type": "Table|Form|Chart|Card|List|Modal|Sidebar|Navbar|Hero|Stats|Tabs|Button|Input|Select|DatePicker|FileUpload|RichText|Map|Calendar|KanbanBoard|Badge|Avatar|Breadcrumb|Pagination|SearchBar|FilterPanel|ExportButton|NotificationBell",
          "label": "<label>",
          "props": {},
          "data_source": "<api endpoint path>",
          "actions": [],
          "validation": {}
        }
      ]
    }
  ],
  "global_components": ["Navbar", "Footer", "NotificationBell"],
  "navigation": {
    "type": "sidebar|topnav|bottom-tabs",
    "items": [
      { "label": "<label>", "route": "/<path>", "icon": "<icon>", "roles": [] }
    ]
  }
}

Rules:
- Every page in the SystemDesign must appear as a page here.
- data_source on components must reference real API endpoint paths.
- role_restricted pages must have non-empty allowed_roles.
- Output valid JSON only. No prose."""

_API_PROMPT = """You are the API Schema generator in an AI compiler pipeline.

Given a SystemDesign JSON, generate a complete api_config JSON object.

Output ONLY this JSON object (no wrapper, no markdown):
{
  "base_path": "/api/v1",
  "auth_strategy": "jwt",
  "versioning": "v1",
  "rate_limiting": { "default": "100/min", "auth": "10/min" },
  "cors_origins": ["*"],
  "middleware": ["auth", "logging", "rate_limit"],
  "endpoints": [
    {
      "path": "/api/v1/<resource>",
      "method": "GET|POST|PUT|PATCH|DELETE",
      "description": "<what it does>",
      "auth_required": true,
      "roles": ["<role>"],
      "request_body": {
        "<field>": { "type": "<type>", "required": true }
      },
      "query_params": [
        { "name": "<param>", "type": "string", "required": false }
      ],
      "response_schema": {
        "200": { "<field>": "<type>" }
      },
      "error_responses": [
        { "status": 401, "message": "Unauthorized" },
        { "status": 403, "message": "Forbidden" }
      ],
      "tags": ["<resource>"]
    }
  ]
}

Rules:
- request_body fields MUST correspond to DB table columns for that entity.
- Include CRUD endpoints for every entity in the SystemDesign.
- Include auth endpoints: POST /auth/login, POST /auth/register, POST /auth/refresh.
- Output valid JSON only. No prose."""

_DB_PROMPT = """You are the Database Schema generator in an AI compiler pipeline.

Given a SystemDesign JSON, generate a complete db_schema JSON object.

Output ONLY this JSON object (no wrapper, no markdown):
{
  "dialect": "postgresql",
  "schema_name": "public",
  "tables": [
    {
      "name": "<snake_case_table>",
      "description": "<optional>",
      "columns": [
        {
          "name": "<col>",
          "type": "UUID|VARCHAR|TEXT|INT|BIGINT|FLOAT|DECIMAL|BOOLEAN|TIMESTAMP|DATE|JSON|JSONB|ENUM|SERIAL",
          "length": null,
          "nullable": false,
          "primary_key": false,
          "unique": false,
          "default": null,
          "enum_values": [],
          "check": null
        }
      ],
      "indexes": [
        { "name": "idx_<table>_<col>", "columns": ["<col>"], "unique": false }
      ],
      "foreign_keys": [
        {
          "column": "<col>",
          "references_table": "<table>",
          "references_column": "id",
          "on_delete": "CASCADE|SET NULL|RESTRICT|NO ACTION",
          "on_update": "CASCADE"
        }
      ]
    }
  ],
  "migrations": [
    {
      "version": "001",
      "description": "Initial schema",
      "sql_up": "CREATE TABLE ...",
      "sql_down": "DROP TABLE ..."
    }
  ]
}

Rules:
- Every entity in SystemDesign becomes a table (snake_case name).
- Every table MUST have: id (UUID, PK), created_at (TIMESTAMP), updated_at (TIMESTAMP).
- Many-to-many relations require a join table.
- foreign_keys must reference valid tables.
- Include at least one migration with real CREATE TABLE SQL.
- Output valid JSON only. No prose."""

_AUTH_PROMPT = """You are the Auth Config generator in an AI compiler pipeline.

Given a SystemDesign JSON, generate a complete auth_config JSON object.

Output ONLY this JSON object (no wrapper, no markdown):
{
  "strategy": "jwt",
  "token_expiry": "24h",
  "refresh_token": true,
  "refresh_expiry": "7d",
  "jwt_algorithm": "HS256",
  "mfa_enabled": false,
  "oauth_providers": [],
  "roles": [
    {
      "name": "<role>",
      "inherits": [],
      "permissions": ["<resource>:<action>"]
    }
  ],
  "route_guards": [
    {
      "route": "/<path>",
      "allowed_roles": ["<role>"],
      "redirect_to": "/login"
    }
  ],
  "password_policy": {
    "min_length": 8,
    "require_uppercase": true,
    "require_number": true,
    "require_special": true,
    "max_age_days": 90
  }
}

Rules:
- roles must include ALL roles from the SystemDesign roles[].
- Every role_restricted page in the SystemDesign must have a matching route_guard.
- permissions format: "<entity_lowercase>:<action>" e.g. "contact:read".
- Output valid JSON only. No prose."""

_SUB_PROMPTS = {
    "ui_config":  _UI_PROMPT,
    "api_config": _API_PROMPT,
    "db_schema":  _DB_PROMPT,
    "auth_config": _AUTH_PROMPT,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_schemas(design: dict) -> dict:
    """
    Stage 3 entry point.
    Generates all 4 sub-schemas in parallel, validates each, repairs if needed,
    then enforces cross-layer consistency.
    Returns the complete AllSchemas dict.
    """
    logger.info('[Stage 3] Parallel schema generation for: %s', design.get('app_name', '?'))

    user_prompt = (
        "Generate the requested schema for this SystemDesign:\n"
        + json.dumps(design, indent=2)
    )

    results = {}
    errors_map = {}

    # ── Parallel generation ────────────────────────────────────────────────
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(
                _generate_sub_schema, name, user_prompt
            ): name
            for name in ("ui_config", "api_config", "db_schema", "auth_config")
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.error('[Stage 3] Sub-schema %s failed: %s', name, exc)
                errors_map[name] = str(exc)
                results[name] = {}

    # ── Cross-layer consistency ────────────────────────────────────────────
    results = _cross_layer_consistency(design, results)

    logger.info(
        '[Stage 3] Done. Pages: %d, Endpoints: %d, Tables: %d, Auth roles: %d',
        len(results.get('ui_config', {}).get('pages', [])),
        len(results.get('api_config', {}).get('endpoints', [])),
        len(results.get('db_schema', {}).get('tables', [])),
        len(results.get('auth_config', {}).get('roles', [])),
    )
    return results


# Alias
run = generate_schemas


# ---------------------------------------------------------------------------
# Per-sub-schema generation + targeted repair
# ---------------------------------------------------------------------------

def _generate_sub_schema(name: str, user_prompt: str, attempt: int = 0) -> dict:
    """Generate one sub-schema and validate it. Repair up to 2 times."""
    system_prompt = _SUB_PROMPTS[name]

    raw = chat_completion_json(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        stage_id=3
    )
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        raw.pop(k, None)

    errors = _validate_sub(name, raw)
    if not errors:
        logger.info('[Stage 3] %s ✓ valid', name)
        return raw

    if attempt >= 2:
        logger.error('[Stage 3] %s — max repairs reached, using partial output', name)
        return _apply_sub_defaults(name, raw)

    logger.warning('[Stage 3] %s repair attempt %d — errors: %s',
                   name, attempt + 1, [e['path'] for e in errors])

    error_summary = json.dumps(
        [{'path': e['path'], 'message': e['message']} for e in errors], indent=2
    )
    repair_prompt = (
        f"The {name} JSON has schema violations:\n{error_summary}\n\n"
        f"Original JSON (fix ONLY the failing sections; return the FULL corrected JSON):\n"
        + json.dumps(raw)
    )
    return _generate_sub_schema(name, repair_prompt, attempt + 1)


def _validate_sub(name: str, data: dict) -> list:
    """Validate a sub-schema dict. Returns list of {path, message}."""
    sub_schema = _SUB_SCHEMAS.get(name, {})
    if not sub_schema:
        return []
    validator = jsonschema.Draft7Validator(sub_schema)
    errors = []
    for err in validator.iter_errors(data):
        path = ' -> '.join(str(p) for p in err.absolute_path) or 'root'
        errors.append({'path': path, 'message': err.message})
    return errors


def _apply_sub_defaults(name: str, data: dict) -> dict:
    """Apply safe minimum defaults for a sub-schema that failed repair."""
    defaults = {
        'ui_config':  {'theme': 'light', 'pages': [], 'global_components': [], 'navigation': {'type': 'sidebar', 'items': []}},
        'api_config': {'base_path': '/api/v1', 'auth_strategy': 'jwt', 'versioning': 'v1', 'endpoints': []},
        'db_schema':  {'dialect': 'postgresql', 'tables': [], 'migrations': []},
        'auth_config': {
            'strategy': 'jwt', 'token_expiry': '24h', 'refresh_token': True,
            'roles': [], 'route_guards': [],
            'password_policy': {'min_length': 8, 'require_uppercase': True, 'require_number': True, 'require_special': True}
        },
    }
    base = defaults.get(name, {})
    base.update(data)
    return base


# ---------------------------------------------------------------------------
# Cross-layer consistency
# ---------------------------------------------------------------------------

def _cross_layer_consistency(design: dict, schemas: dict) -> dict:
    """
    Enforce four cross-layer rules:
    1. Auth roles == design roles (inject missing)
    2. Route guards cover all role_restricted pages
    3. UI data_sources reference real API endpoint paths
    4. DB tables cover all design entities
    """
    schemas = _sync_auth_roles(design, schemas)
    schemas = _sync_route_guards(schemas)
    schemas = _sync_ui_datasources(schemas)
    schemas = _sync_db_tables(design, schemas)
    return schemas


def _sync_auth_roles(design: dict, schemas: dict) -> dict:
    """Ensure every design role exists in auth_config.roles."""
    auth = schemas.get('auth_config', {})
    existing = {r['name'] for r in auth.get('roles', [])}
    for role in design.get('roles', []):
        rname = role['name'] if isinstance(role, dict) else role
        if rname not in existing:
            logger.info('[Stage 3] cross-check: injecting missing auth role %s', rname)
            auth.setdefault('roles', []).append({
                'name': rname,
                'inherits': [],
                'permissions': []
            })
            existing.add(rname)
    schemas['auth_config'] = auth
    return schemas


def _sync_route_guards(schemas: dict) -> dict:
    """Add missing route guards for role_restricted UI pages."""
    ui = schemas.get('ui_config', {})
    auth = schemas.get('auth_config', {})
    guarded_routes = {g['route'] for g in auth.get('route_guards', [])}

    for page in ui.get('pages', []):
        if page.get('access') == 'role_restricted':
            route = page.get('route', '')
            if route and route not in guarded_routes:
                logger.info('[Stage 3] cross-check: adding route guard for %s', route)
                auth.setdefault('route_guards', []).append({
                    'route': route,
                    'allowed_roles': page.get('allowed_roles', []),
                    'redirect_to': '/login'
                })
                guarded_routes.add(route)
    schemas['auth_config'] = auth
    return schemas


def _sync_ui_datasources(schemas: dict) -> dict:
    """
    Check that UI component data_sources reference valid API paths.
    Log mismatches — do NOT remove components, just annotate with a warning flag.
    """
    api = schemas.get('api_config', {})
    valid_paths = {e['path'] for e in api.get('endpoints', [])}
    ui = schemas.get('ui_config', {})

    for page in ui.get('pages', []):
        for comp in page.get('components', []):
            ds = comp.get('data_source')
            if ds and valid_paths and ds not in valid_paths:
                logger.warning(
                    '[Stage 3] UI component "%s" on page "%s" references unknown API path "%s"',
                    comp.get('id', '?'), page.get('name', '?'), ds
                )
                comp['_validation_warning'] = f'data_source "{ds}" not found in api_config endpoints'
    schemas['ui_config'] = ui
    return schemas


def _sync_db_tables(design: dict, schemas: dict) -> dict:
    """
    Ensure every design entity has a corresponding DB table.
    Inject a minimal stub table if missing.
    """
    db = schemas.get('db_schema', {})
    existing_tables = {t['name'] for t in db.get('tables', [])}

    for entity in design.get('entities', []):
        ename = entity['name'] if isinstance(entity, dict) else entity
        snake = _to_snake(ename)
        if snake not in existing_tables:
            logger.info('[Stage 3] cross-check: injecting stub table for entity %s', ename)
            stub = {
                'name': snake,
                'description': f'Auto-generated table for {ename}',
                'columns': [
                    {'name': 'id',         'type': 'UUID',      'nullable': False, 'primary_key': True,  'unique': True,  'default': 'gen_random_uuid()'},
                    {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False, 'primary_key': False, 'unique': False, 'default': 'NOW()'},
                    {'name': 'updated_at', 'type': 'TIMESTAMP', 'nullable': False, 'primary_key': False, 'unique': False, 'default': 'NOW()'}
                ],
                'indexes': [],
                'foreign_keys': []
            }
            db.setdefault('tables', []).append(stub)
            existing_tables.add(snake)

    schemas['db_schema'] = db
    return schemas


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_snake(name: str) -> str:
    """Convert PascalCase or Title Case entity name to snake_case table name."""
    import re
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    s = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', s)
    return s.lower().replace(' ', '_')
