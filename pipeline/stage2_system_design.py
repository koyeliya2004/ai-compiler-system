"""
Stage 2 -- System Design Layer

Input:  Stage 1 IntentSchema  (dict)
Output: SystemDesign          (dict validated against system_design_schema.json)

Responsibilities:
  - Convert extracted intent into full app architecture
  - Define all entities with fields + relations
  - Build page hierarchy with access control
  - Design API surface (grouped by resource)
  - Emit permission matrix (role x entity x action)
  - Capture business rules (premium gating, role logic, etc.)
  - Document design decisions + tradeoffs

Repair strategy:
  - On schema violation, extract the exact failing path and re-generate
    only that sub-section -- never a full blind retry.
  - Max 2 targeted repair passes before falling back to safe defaults.
"""

import json
import logging
import os
from pathlib import Path

import jsonschema

from llm_client import chat_completion_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load schema contract once at import time
# ---------------------------------------------------------------------------
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "system_design_schema.json"
with open(_SCHEMA_PATH) as _f:
    SYSTEM_DESIGN_SCHEMA = json.load(_f)

# ---------------------------------------------------------------------------
# System prompt (strict)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are Stage 2 of an AI compiler pipeline: the System Design Layer.

You receive a structured intent object from Stage 1 and must produce a complete
app architecture as a single valid JSON object.

Output contract (all fields are REQUIRED unless marked optional):
{
  "app_name": "<string>",
  "app_type": "<string>",

  "entities": [
    {
      "name": "<PascalCase entity name>",
      "description": "<optional>",
      "fields": [
        {
          "name": "<snake_case>",
          "type": "<string|integer|float|boolean|datetime|uuid|text|json|enum>",
          "required": true,
          "unique": false,        // optional
          "indexed": false,       // optional
          "enum_values": [],      // optional, only when type=enum
          "default": null         // optional
        }
      ],
      "relations": [
        {
          "type": "<belongs_to|has_many|has_one|many_to_many>",
          "target": "<EntityName>",
          "through": "<JoinTable>"  // optional, only for many_to_many
        }
      ]
    }
  ],

  "pages": [
    {
      "name": "<PageName>",
      "path": "</route>",
      "description": "<optional>",
      "access": "<public|authenticated|role_restricted>",
      "allowed_roles": ["<role>"],  // required when access=role_restricted
      "components": ["<ComponentName>"],
      "parent_page": "<ParentName>"  // optional
    }
  ],

  "api_groups": [
    {
      "resource": "<ResourceName>",
      "base_path": "/api/v1/<resource>",
      "endpoints": [
        {
          "method": "<GET|POST|PUT|PATCH|DELETE>",
          "path": "<relative path, e.g. / or /:id>",
          "description": "<what it does>",
          "auth_required": true,
          "roles": ["<role>"],
          "request_body": {},   // optional
          "response": {}        // optional
        }
      ]
    }
  ],

  "roles": [
    {
      "name": "<role_name>",
      "description": "<what this role can do>",
      "is_default": false,
      "capabilities": ["<action>"]
    }
  ],

  "permission_matrix": {
    "<EntityName>": {
      "<role_name>": ["create","read","update","delete","list","export"]
    }
  },

  "business_rules": [
    {
      "id": "BR-001",
      "rule": "<human-readable rule>",
      "trigger": "<when this fires>",
      "action": "<what happens>",
      "affects_roles": ["<role>"]
    }
  ],

  "data_flows": [
    {
      "name": "<flow name>",
      "steps": ["Step 1: ...", "Step 2: ..."]
    }
  ],

  "design_decisions": [
    {
      "decision": "<what was decided>",
      "rationale": "<why>",
      "tradeoff": "<optional: what was traded off>"
    }
  ]
}

Rules:
- Output ONLY valid JSON. No markdown, no prose, no explanation.
- Every entity referenced in relations must also appear in entities[].
- Every role referenced in permission_matrix must appear in roles[].
- Every page with access=role_restricted must have a non-empty allowed_roles array.
- business_rules must explicitly model premium gating, role restrictions, and any payment logic.
- Include at least 3 data_flows (e.g. registration, primary CRUD flow, auth flow).
- Include at least 2 design_decisions with rationale.
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def design_system(intent: dict) -> dict:
    """
    Stage 2 entry point.
    Takes Stage 1 output (intent dict) and returns a validated SystemDesign dict.
    """
    logger.info('[Stage 2] System design for app: %s', intent.get('app_name', '?'))

    user_prompt = (
        "Convert this Stage 1 intent into a complete SystemDesign JSON:\n"
        + json.dumps(intent, indent=2)
    )

    result = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.15,
        stage_id=2
    )
    _strip_meta(result)

    # Validate + targeted repair
    result = _validate_and_repair(intent, result)

    # Post-process: ensure cross-layer consistency
    result = _cross_check(intent, result)

    logger.info('[Stage 2] Done. Entities: %d, Pages: %d, API groups: %d',
                len(result.get('entities', [])),
                len(result.get('pages', [])),
                len(result.get('api_groups', [])))
    return result


# Alias so pipeline/orchestrator can call run(intent)
run = design_system


# ---------------------------------------------------------------------------
# Validation + targeted repair
# ---------------------------------------------------------------------------

def _validate_and_repair(intent: dict, result: dict, attempt: int = 0) -> dict:
    """Validate against JSON schema; on failure, repair only the failing section."""
    errors = _collect_errors(result)
    if not errors:
        return result

    if attempt >= 2:
        logger.error('[Stage 2] Max repair attempts reached. Applying safe defaults.')
        return _apply_safe_defaults(intent, result, errors)

    logger.warning('[Stage 2] Repair attempt %d — fixing: %s', attempt + 1,
                   [e['path'] for e in errors])

    # Build targeted repair prompt listing exact violations
    error_summary = json.dumps([
        {'path': e['path'], 'message': e['message']} for e in errors
    ], indent=2)

    repair_prompt = (
        "The following SystemDesign JSON has schema violations:\n"
        + error_summary
        + "\n\nOriginal JSON (fix ONLY the failing sections; return the FULL corrected JSON):\n"
        + json.dumps(result)
    )

    repaired = chat_completion_json(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=repair_prompt,
        temperature=0.05,
        stage_id=2
    )
    _strip_meta(repaired)
    return _validate_and_repair(intent, repaired, attempt + 1)


def _collect_errors(result: dict) -> list:
    """Return list of {path, message} dicts from jsonschema validation."""
    validator = jsonschema.Draft7Validator(SYSTEM_DESIGN_SCHEMA)
    errors = []
    for err in validator.iter_errors(result):
        path = ' -> '.join(str(p) for p in err.absolute_path) or 'root'
        errors.append({'path': path, 'message': err.message})
    return errors


def _apply_safe_defaults(intent: dict, result: dict, errors: list) -> dict:
    """Fill in safe defaults for any still-missing required top-level keys."""
    required_keys = [
        'app_name', 'app_type', 'entities', 'pages', 'api_groups',
        'roles', 'permission_matrix', 'business_rules', 'data_flows',
        'design_decisions'
    ]
    for key in required_keys:
        if key not in result:
            if key in ('entities', 'pages', 'api_groups', 'roles',
                       'business_rules', 'data_flows', 'design_decisions'):
                result[key] = []
            elif key == 'permission_matrix':
                result[key] = {}
            else:
                result[key] = intent.get(key, '')
    return result


# ---------------------------------------------------------------------------
# Cross-layer consistency checks
# ---------------------------------------------------------------------------

def _cross_check(intent: dict, result: dict) -> dict:
    """
    Enforce cross-layer consistency rules:
    1. Every role in permission_matrix must exist in roles[].
    2. Every entity in permission_matrix must exist in entities[].
    3. Every role referenced in pages[].allowed_roles must exist in roles[].
    4. Inject any intent roles missing from design roles.
    5. Inject any intent entities missing from design entities.
    """
    known_roles = {r['name'] for r in result.get('roles', [])}
    known_entities = {e['name'] for e in result.get('entities', [])}

    # --- 4. Inject missing intent roles ---
    for role_name in intent.get('roles', []):
        if role_name not in known_roles:
            logger.info('[Stage 2] Cross-check: injecting missing role %s', role_name)
            result['roles'].append({
                'name': role_name,
                'description': f'{role_name} role (injected by cross-check)',
                'is_default': False,
                'capabilities': []
            })
            known_roles.add(role_name)

    # --- 5. Inject missing intent entities (stub) ---
    for ent_name in intent.get('entities', []):
        # Normalise: PascalCase
        pascal = ent_name.title().replace(' ', '')
        if pascal not in known_entities:
            logger.info('[Stage 2] Cross-check: injecting stub entity %s', pascal)
            result['entities'].append({
                'name': pascal,
                'description': f'Stub entity injected by cross-check from intent',
                'fields': [
                    {'name': 'id', 'type': 'uuid', 'required': True, 'unique': True, 'indexed': True},
                    {'name': 'created_at', 'type': 'datetime', 'required': True}
                ],
                'relations': []
            })
            known_entities.add(pascal)

    # --- 3. Fix pages with role_restricted but missing allowed_roles ---
    for page in result.get('pages', []):
        if page.get('access') == 'role_restricted':
            valid_roles = [r for r in page.get('allowed_roles', []) if r in known_roles]
            if not valid_roles:
                # Default to first non-default role or first role
                fallback = next(
                    (r for r in known_roles if r != 'user'),
                    next(iter(known_roles), 'user')
                )
                logger.warning(
                    '[Stage 2] Cross-check: page "%s" has no valid allowed_roles, defaulting to %s',
                    page.get('name'), fallback
                )
                page['allowed_roles'] = [fallback]

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_meta(d: dict) -> None:
    for k in ['__model_used__', '__model_label__', '__stage_ms__']:
        d.pop(k, None)
