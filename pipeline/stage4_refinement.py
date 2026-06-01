"""
Stage 4 -- Refinement Layer

Input:  intent (Stage 1), design (Stage 2), schemas (Stage 3)
Output: RefinedOutput = {
    "intent":  <Stage1 dict, unchanged>,
    "design":  <Stage2 dict, possibly patched>,
    "schemas": <Stage3 dict, possibly patched>,
    "refinement_report": {
        "consistency_score": 0-100,
        "conflicts_found":   [...],
        "conflicts_resolved": [...],
        "assumptions_made":  [...],
        "warnings":          [...],
        "unresolvable":      [...]
    }
}

The Refinement Layer is a deterministic rules engine (no LLM needed for most
fixes). An LLM call is made ONLY when a conflict is semantically ambiguous and
cannot be resolved with a hard rule.

Conflict categories checked (15 rules):
  A. API <-> DB field alignment
  B. UI route  <-> API endpoint coverage
  C. Auth role <-> Design role completeness
  D. Permission matrix <-> Auth permissions
  E. Business rule <-> Schema field existence
  F. Relation FK <-> Referenced table existence
  G. Enum field <-> Enum values defined
  H. Required field <-> Nullable flag
  I. Page component data_source <-> API path
  J. Role-restricted page <-> Route guard
  K. Many-to-many entity <-> Join table
  L. Premium gating rule <-> subscription/plan field
  M. Analytics page <-> Admin role guard
  N. Payment feature <-> payments/stripe table
  O. Orphan foreign key columns
"""

import json
import logging
import re
from copy import deepcopy
from typing import Any

from llm_client import chat_completion_json

logger = logging.getLogger(__name__)


# ============================================================
# Public entry point
# ============================================================

def refine(intent: dict, design: dict, schemas: dict) -> dict:
    """
    Stage 4 entry point.
    Returns a RefinedOutput dict with patched design + schemas
    and a full refinement_report.
    """
    logger.info('[Stage 4] Refinement started for app: %s', design.get('app_name', '?'))

    design  = deepcopy(design)
    schemas = deepcopy(schemas)

    report = {
        'consistency_score': 0,
        'conflicts_found':    [],
        'conflicts_resolved': [],
        'assumptions_made':   [],
        'warnings':           [],
        'unresolvable':       [],
    }

    # ----- Run all conflict checks -----
    ctx = _Context(intent, design, schemas, report)

    _check_api_db_alignment(ctx)           # A
    _check_ui_api_coverage(ctx)            # B
    _check_auth_role_completeness(ctx)     # C
    _check_permission_matrix(ctx)          # D
    _check_business_rule_fields(ctx)       # E
    _check_fk_table_existence(ctx)         # F
    _check_enum_values_defined(ctx)        # G
    _check_required_nullable(ctx)          # H
    _check_datasource_api_paths(ctx)       # I
    _check_role_restricted_guards(ctx)     # J
    _check_m2m_join_tables(ctx)            # K
    _check_premium_gating_field(ctx)       # L
    _check_analytics_admin_guard(ctx)      # M
    _check_payment_table(ctx)              # N
    _check_orphan_fk_columns(ctx)          # O

    # ----- LLM-assisted resolution for ambiguous conflicts -----
    if ctx.ambiguous:
        _llm_resolve_ambiguous(ctx)

    # ----- Compute consistency score -----
    report['consistency_score'] = _score(report)

    logger.info(
        '[Stage 4] Score: %d/100 | found: %d | resolved: %d | unresolvable: %d',
        report['consistency_score'],
        len(report['conflicts_found']),
        len(report['conflicts_resolved']),
        len(report['unresolvable']),
    )

    return {
        'intent':           intent,
        'design':           ctx.design,
        'schemas':          ctx.schemas,
        'refinement_report': report,
    }


# Alias for pipeline __init__
run = refine


# ============================================================
# Context object
# ============================================================

class _Context:
    """Mutable container shared across all rule functions."""

    def __init__(self, intent, design, schemas, report):
        self.intent   = intent
        self.design   = design
        self.schemas  = schemas
        self.report   = report
        self.ambiguous: list[dict] = []  # conflicts needing LLM

    # Shorthand accessors
    @property
    def ui(self):   return self.schemas.get('ui_config',   {})
    @property
    def api(self):  return self.schemas.get('api_config',  {})
    @property
    def db(self):   return self.schemas.get('db_schema',   {})
    @property
    def auth(self): return self.schemas.get('auth_config', {})

    def found(self, rule_id: str, msg: str, severity='error'):
        self.report['conflicts_found'].append(
            {'rule': rule_id, 'severity': severity, 'message': msg}
        )

    def resolved(self, rule_id: str, msg: str):
        self.report['conflicts_resolved'].append({'rule': rule_id, 'fix': msg})

    def warn(self, msg: str):
        self.report['warnings'].append(msg)

    def assume(self, msg: str):
        self.report['assumptions_made'].append(msg)

    def unresolvable(self, rule_id: str, msg: str):
        self.report['unresolvable'].append({'rule': rule_id, 'message': msg})


# ============================================================
# Conflict rules
# ============================================================

# ---- A. API <-> DB field alignment -------------------------

def _check_api_db_alignment(ctx: _Context):
    """
    Every POST/PUT/PATCH request_body field must correspond to a DB column
    in the matching table.
    """
    db_tables = {t['name']: {c['name'] for c in t.get('columns', [])}
                 for t in ctx.db.get('tables', [])}

    for ep in ctx.api.get('endpoints', []):
        if ep['method'] not in ('POST', 'PUT', 'PATCH'):
            continue
        body = ep.get('request_body', {})
        if not body:
            continue

        # Infer table name from endpoint path, e.g. /api/v1/contacts -> contacts
        table_name = _infer_table_from_path(ep['path'])
        if table_name not in db_tables:
            continue  # can't validate without a matching table

        valid_cols = db_tables[table_name]
        for field in body:
            if field not in valid_cols and field not in ('id', 'password', 'confirm_password'):
                ctx.found('A', f'API {ep["method"]} {ep["path"]}: body field "{field}" not in DB table "{table_name}"')
                # Auto-fix: add the column to the DB table
                _add_column(ctx, table_name, field, 'VARCHAR')
                ctx.resolved('A', f'Added column "{field}" (VARCHAR) to table "{table_name}"')


# ---- B. UI route <-> API coverage --------------------------

def _check_ui_api_coverage(ctx: _Context):
    """
    Every authenticated/role_restricted page that has Form/Table components
    must have at least one API endpoint that maps to its route resource.
    """
    api_resources = {_infer_table_from_path(e['path'])
                     for e in ctx.api.get('endpoints', [])}

    for page in ctx.ui.get('pages', []):
        if page.get('access') == 'public':
            continue
        has_data_component = any(
            c.get('type') in ('Table', 'Form', 'List', 'KanbanBoard', 'Calendar')
            for c in page.get('components', [])
        )
        if not has_data_component:
            continue

        route_resource = page.get('route', '').strip('/').split('/')[-1].rstrip('s')
        plural = route_resource + 's'
        if plural not in api_resources and route_resource not in api_resources:
            ctx.found('B', f'Page "{page["name"]}" has data components but no matching API resource "{plural}"',
                      severity='warning')
            ctx.warn(f'No API endpoint found for page "{page["name"]}" — may need manual endpoint')


# ---- C. Auth role completeness -----------------------------

def _check_auth_role_completeness(ctx: _Context):
    design_roles = {r['name'] if isinstance(r, dict) else r
                    for r in ctx.design.get('roles', [])}
    auth_roles   = {r['name'] for r in ctx.auth.get('roles', [])}
    missing = design_roles - auth_roles

    for role in missing:
        ctx.found('C', f'Role "{role}" in design but missing from auth_config.roles')
        ctx.schemas.setdefault('auth_config', {}).setdefault('roles', []).append({
            'name': role, 'inherits': [], 'permissions': []
        })
        ctx.resolved('C', f'Injected role "{role}" into auth_config.roles')


# ---- D. Permission matrix <-> Auth permissions -------------

def _check_permission_matrix(ctx: _Context):
    """
    Every (entity, role) CRUD flag set in the design permission_matrix
    should generate a matching permission string in auth_config.
    """
    matrix    = ctx.design.get('permission_matrix', {})
    auth_perms_by_role = {
        r['name']: set(r.get('permissions', []))
        for r in ctx.auth.get('roles', [])
    }

    for entity, role_map in matrix.items():
        entity_key = entity.lower()
        for role, actions in role_map.items():
            if role not in auth_perms_by_role:
                continue
            for action, allowed in (actions.items() if isinstance(actions, dict) else {}):
                if not allowed:
                    continue
                perm = f'{entity_key}:{action}'
                if perm not in auth_perms_by_role[role]:
                    # Auto-add permission
                    for r in ctx.schemas['auth_config']['roles']:
                        if r['name'] == role:
                            r.setdefault('permissions', []).append(perm)
                            break
                    ctx.resolved('D', f'Added permission "{perm}" to role "{role}"')


# ---- E. Business rule <-> Schema field existence -----------

def _check_business_rule_fields(ctx: _Context):
    """Business rules referencing a field must have that field in the DB."""
    all_columns = set()
    for t in ctx.db.get('tables', []):
        for c in t.get('columns', []):
            all_columns.add(c['name'])

    for rule in ctx.design.get('business_rules', []):
        rule_text = str(rule)
        # Extract field-like tokens (snake_case words inside the rule text)
        tokens = re.findall(r'\b[a-z][a-z0-9_]{2,}\b', rule_text)
        for tok in tokens:
            if '_' in tok and tok not in all_columns:
                ctx.warn(f'Business rule may reference field "{tok}" not found in any DB table')


# ---- F. FK <-> Referenced table existence ------------------

def _check_fk_table_existence(ctx: _Context):
    table_names = {t['name'] for t in ctx.db.get('tables', [])}

    for table in ctx.db.get('tables', []):
        for fk in table.get('foreign_keys', []):
            ref_table = fk.get('references_table')
            if ref_table and ref_table not in table_names:
                ctx.found('F', f'Table "{table["name"]}" FK references non-existent table "{ref_table}"')
                # Stub the missing table
                stub = {
                    'name': ref_table,
                    'description': f'Auto-stubbed from FK in {table["name"]}',
                    'columns': [
                        {'name': 'id', 'type': 'UUID', 'nullable': False, 'primary_key': True, 'unique': True, 'default': 'gen_random_uuid()'},
                        {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False, 'primary_key': False, 'unique': False, 'default': 'NOW()'},
                        {'name': 'updated_at', 'type': 'TIMESTAMP', 'nullable': False, 'primary_key': False, 'unique': False, 'default': 'NOW()'}
                    ],
                    'indexes': [], 'foreign_keys': []
                }
                ctx.schemas['db_schema'].setdefault('tables', []).append(stub)
                table_names.add(ref_table)
                ctx.resolved('F', f'Stubbed missing FK-referenced table "{ref_table}"')


# ---- G. Enum field <-> Enum values defined -----------------

def _check_enum_values_defined(ctx: _Context):
    for table in ctx.db.get('tables', []):
        for col in table.get('columns', []):
            if col.get('type') == 'ENUM' and not col.get('enum_values'):
                ctx.found('G', f'Column "{table["name"]}.{col["name"]}" is ENUM but has no enum_values')
                col['enum_values'] = ['active', 'inactive']  # safe default
                ctx.resolved('G', f'Added default enum_values [active, inactive] to "{table["name"]}.{col["name"]}"')
                ctx.assume(f'ENUM "{table["name"]}.{col["name"]}": defaulted to [active, inactive] — review required')


# ---- H. Required field <-> Nullable flag -------------------

def _check_required_nullable(ctx: _Context):
    for table in ctx.db.get('tables', []):
        for col in table.get('columns', []):
            if col.get('primary_key') and col.get('nullable', True):
                ctx.found('H', f'Primary key "{table["name"]}.{col["name"]}" must not be nullable')
                col['nullable'] = False
                ctx.resolved('H', f'Set nullable=false on PK "{table["name"]}.{col["name"]}"')


# ---- I. Component data_source <-> API paths ----------------

def _check_datasource_api_paths(ctx: _Context):
    api_paths = {e['path'] for e in ctx.api.get('endpoints', [])}

    for page in ctx.ui.get('pages', []):
        for comp in page.get('components', []):
            ds = comp.get('data_source')
            if ds and ds not in api_paths:
                ctx.found('I', f'Component "{comp.get("id")}" on page "{page["name"]}" '
                           f'has data_source "{ds}" not in api endpoints', severity='warning')
                # Best-effort: find closest endpoint
                closest = _closest_path(ds, api_paths)
                if closest:
                    comp['data_source'] = closest
                    ctx.resolved('I', f'Corrected data_source to "{closest}" for "{comp.get("id")}"')


# ---- J. Role-restricted page <-> Route guard ---------------

def _check_role_restricted_guards(ctx: _Context):
    guards = {g['route'] for g in ctx.auth.get('route_guards', [])}

    for page in ctx.ui.get('pages', []):
        if page.get('access') == 'role_restricted':
            route = page.get('route', '')
            if route and route not in guards:
                ctx.found('J', f'Role-restricted page "{page["name"]}" at "{route}" has no route guard')
                ctx.schemas['auth_config'].setdefault('route_guards', []).append({
                    'route': route,
                    'allowed_roles': page.get('allowed_roles', []),
                    'redirect_to': '/login'
                })
                guards.add(route)
                ctx.resolved('J', f'Added route guard for "{route}"')


# ---- K. Many-to-many <-> Join table ------------------------

def _check_m2m_join_tables(ctx: _Context):
    table_names = {t['name'] for t in ctx.db.get('tables', [])}

    for entity in ctx.design.get('entities', []):
        for rel in (entity.get('relations', []) if isinstance(entity, dict) else []):
            if rel.get('type') == 'many_to_many':
                a = _to_snake(entity['name'])
                b = _to_snake(rel.get('target', ''))
                join = f'{a}_{b}'
                join_alt = f'{b}_{a}'
                if join not in table_names and join_alt not in table_names:
                    ctx.found('K', f'Many-to-many between "{a}" and "{b}" has no join table')
                    ctx.schemas['db_schema'].setdefault('tables', []).append({
                        'name': join,
                        'description': f'Join table for {a} <-> {b}',
                        'columns': [
                            {'name': 'id',         'type': 'UUID',      'nullable': False, 'primary_key': True, 'unique': True,  'default': 'gen_random_uuid()'},
                            {'name': f'{a}_id',    'type': 'UUID',      'nullable': False, 'primary_key': False, 'unique': False, 'default': None},
                            {'name': f'{b}_id',    'type': 'UUID',      'nullable': False, 'primary_key': False, 'unique': False, 'default': None},
                            {'name': 'created_at', 'type': 'TIMESTAMP', 'nullable': False, 'primary_key': False, 'unique': False, 'default': 'NOW()'}
                        ],
                        'indexes': [{'name': f'idx_{join}_pair', 'columns': [f'{a}_id', f'{b}_id'], 'unique': True}],
                        'foreign_keys': [
                            {'column': f'{a}_id', 'references_table': a, 'references_column': 'id', 'on_delete': 'CASCADE', 'on_update': 'CASCADE'},
                            {'column': f'{b}_id', 'references_table': b, 'references_column': 'id', 'on_delete': 'CASCADE', 'on_update': 'CASCADE'},
                        ]
                    })
                    table_names.add(join)
                    ctx.resolved('K', f'Created join table "{join}" for M2M relation')


# ---- L. Premium gating <-> plan/subscription field --------

def _check_premium_gating_field(ctx: _Context):
    has_premium = any(
        'premium' in str(r).lower() or 'plan' in str(r).lower()
        for r in ctx.design.get('business_rules', [])
    )
    if not has_premium:
        return

    table_names = {t['name'] for t in ctx.db.get('tables', [])}
    if 'subscriptions' not in table_names and 'plans' not in table_names:
        ctx.found('L', 'Business rules mention premium/plan gating but no subscriptions/plans table found')
        ctx.schemas['db_schema'].setdefault('tables', []).append({
            'name': 'subscriptions',
            'description': 'Auto-generated for premium gating',
            'columns': [
                {'name': 'id',          'type': 'UUID',      'nullable': False, 'primary_key': True,  'unique': True,  'default': 'gen_random_uuid()'},
                {'name': 'user_id',     'type': 'UUID',      'nullable': False, 'primary_key': False, 'unique': False, 'default': None},
                {'name': 'plan',        'type': 'ENUM',      'nullable': False, 'primary_key': False, 'unique': False, 'default': 'free', 'enum_values': ['free', 'basic', 'premium', 'enterprise']},
                {'name': 'status',      'type': 'ENUM',      'nullable': False, 'primary_key': False, 'unique': False, 'default': 'active', 'enum_values': ['active', 'cancelled', 'expired', 'trialing']},
                {'name': 'expires_at',  'type': 'TIMESTAMP', 'nullable': True,  'primary_key': False, 'unique': False, 'default': None},
                {'name': 'created_at',  'type': 'TIMESTAMP', 'nullable': False, 'primary_key': False, 'unique': False, 'default': 'NOW()'},
                {'name': 'updated_at',  'type': 'TIMESTAMP', 'nullable': False, 'primary_key': False, 'unique': False, 'default': 'NOW()'}
            ],
            'indexes': [{'name': 'idx_subscriptions_user_id', 'columns': ['user_id'], 'unique': False}],
            'foreign_keys': [{'column': 'user_id', 'references_table': 'users', 'references_column': 'id', 'on_delete': 'CASCADE', 'on_update': 'CASCADE'}]
        })
        ctx.resolved('L', 'Created subscriptions table for premium gating support')
        ctx.assume('Premium gating: using subscriptions.plan ENUM field — verify plan names match business logic')


# ---- M. Analytics page <-> Admin role guard ----------------

def _check_analytics_admin_guard(ctx: _Context):
    for page in ctx.ui.get('pages', []):
        name_lower = page.get('name', '').lower()
        route_lower = page.get('route', '').lower()
        if 'analytics' in name_lower or 'analytics' in route_lower:
            if page.get('access') != 'role_restricted':
                ctx.found('M', f'Analytics page "{page["name"]}" is not role-restricted', severity='warning')
                page['access'] = 'role_restricted'
                if 'admin' not in page.get('allowed_roles', []):
                    page.setdefault('allowed_roles', []).append('admin')
                ctx.resolved('M', f'Set analytics page "{page["name"]}" to role_restricted for admin only')


# ---- N. Payment feature <-> payments table -----------------

def _check_payment_table(ctx: _Context):
    features = str(ctx.intent.get('features', [])).lower()
    has_payments = 'payment' in features or 'billing' in features or 'stripe' in features
    if not has_payments:
        return

    table_names = {t['name'] for t in ctx.db.get('tables', [])}
    if 'payments' not in table_names and 'transactions' not in table_names:
        ctx.found('N', 'Intent includes payments but no payments/transactions table in DB schema')
        ctx.schemas['db_schema'].setdefault('tables', []).append({
            'name': 'payments',
            'description': 'Payment transaction records',
            'columns': [
                {'name': 'id',               'type': 'UUID',      'nullable': False, 'primary_key': True,  'unique': True,  'default': 'gen_random_uuid()'},
                {'name': 'user_id',          'type': 'UUID',      'nullable': False, 'primary_key': False, 'unique': False, 'default': None},
                {'name': 'amount',           'type': 'DECIMAL',   'nullable': False, 'primary_key': False, 'unique': False, 'default': None},
                {'name': 'currency',         'type': 'VARCHAR',   'nullable': False, 'primary_key': False, 'unique': False, 'default': 'USD', 'length': 3},
                {'name': 'status',           'type': 'ENUM',      'nullable': False, 'primary_key': False, 'unique': False, 'default': 'pending', 'enum_values': ['pending', 'succeeded', 'failed', 'refunded']},
                {'name': 'stripe_payment_id','type': 'VARCHAR',   'nullable': True,  'primary_key': False, 'unique': True,  'default': None},
                {'name': 'metadata',         'type': 'JSONB',     'nullable': True,  'primary_key': False, 'unique': False, 'default': None},
                {'name': 'created_at',       'type': 'TIMESTAMP', 'nullable': False, 'primary_key': False, 'unique': False, 'default': 'NOW()'},
                {'name': 'updated_at',       'type': 'TIMESTAMP', 'nullable': False, 'primary_key': False, 'unique': False, 'default': 'NOW()'}
            ],
            'indexes': [
                {'name': 'idx_payments_user_id',    'columns': ['user_id'],          'unique': False},
                {'name': 'idx_payments_stripe_id',  'columns': ['stripe_payment_id'],'unique': True}
            ],
            'foreign_keys': [{'column': 'user_id', 'references_table': 'users', 'references_column': 'id', 'on_delete': 'RESTRICT', 'on_update': 'CASCADE'}]
        })
        ctx.resolved('N', 'Created payments table with Stripe fields')
        ctx.assume('Payments: Stripe integration assumed — replace stripe_payment_id if using a different provider')


# ---- O. Orphan FK columns ----------------------------------

def _check_orphan_fk_columns(ctx: _Context):
    """
    Columns named <entity>_id that are NOT declared as foreign_keys.
    """
    table_names = {t['name'] for t in ctx.db.get('tables', [])}

    for table in ctx.db.get('tables', []):
        declared_fk_cols = {fk['column'] for fk in table.get('foreign_keys', [])}
        for col in table.get('columns', []):
            name = col['name']
            if name.endswith('_id') and name != 'id' and name not in declared_fk_cols:
                ref_table = name[:-3]  # strip _id
                if ref_table in table_names:
                    ctx.found('O', f'Column "{table["name"]}.{name}" looks like a FK but is undeclared',
                              severity='warning')
                    table.setdefault('foreign_keys', []).append({
                        'column': name,
                        'references_table': ref_table,
                        'references_column': 'id',
                        'on_delete': 'SET NULL',
                        'on_update': 'CASCADE'
                    })
                    ctx.resolved('O', f'Declared FK "{table["name"]}.{name}" -> "{ref_table}.id"')


# ============================================================
# LLM-assisted resolution (ambiguous conflicts only)
# ============================================================

def _llm_resolve_ambiguous(ctx: _Context):
    if not ctx.ambiguous:
        return

    logger.info('[Stage 4] LLM resolving %d ambiguous conflicts', len(ctx.ambiguous))
    prompt = (
        'You are a schema consistency engine. Resolve these ambiguous conflicts and '
        'return a JSON array of resolutions: [{"rule": "<id>", "fix": "<description>", '
        '"patch": <optional JSON patch dict>}]\n\n'
        'Conflicts:\n' + json.dumps(ctx.ambiguous, indent=2) + '\n\n'
        'Current schemas summary:\n' + json.dumps({
            'tables':    [t['name'] for t in ctx.db.get('tables', [])],
            'endpoints': [e['path'] for e in ctx.api.get('endpoints', [])],
            'roles':     [r['name'] for r in ctx.auth.get('roles', [])],
        }, indent=2)
    )
    result = chat_completion_json(
        system_prompt='Return only a JSON array of resolution objects. No prose.',
        user_prompt=prompt,
        temperature=0.1,
        stage_id=4
    )
    # result might be a list wrapped in a key, or a bare list
    resolutions = result if isinstance(result, list) else result.get('resolutions', [])
    for res in resolutions:
        ctx.report['conflicts_resolved'].append({'rule': res.get('rule', '?'), 'fix': res.get('fix', '')})
        ctx.report['assumptions_made'].append(f'LLM resolved rule {res.get("rule")}: {res.get("fix")}')


# ============================================================
# Consistency scoring
# ============================================================

def _score(report: dict) -> int:
    """
    Score 0-100 based on:
      - Start at 100
      - -5 per unresolved ERROR conflict
      - -2 per WARNING
      - -1 per unresolvable item
      - Bonus: +2 per resolved conflict (max +20)
    """
    found   = report.get('conflicts_found',    [])
    resolved_count = len(report.get('conflicts_resolved', []))
    unresolvable   = len(report.get('unresolvable', []))

    score = 100
    for c in found:
        if c.get('severity') == 'error':
            score -= 5
        elif c.get('severity') == 'warning':
            score -= 2
    score -= unresolvable
    score += min(resolved_count * 2, 20)
    return max(0, min(100, score))


# ============================================================
# Helpers
# ============================================================

def _infer_table_from_path(path: str) -> str:
    """Extract the resource name from an API path and return it as a table name."""
    parts = [p for p in path.strip('/').split('/') if p and not p.startswith('{')]
    if not parts:
        return ''
    last = parts[-1].lower()
    # remove version prefix like v1
    if re.match(r'^v\d+$', last):
        last = parts[-2].lower() if len(parts) > 1 else ''
    return last  # already plural in REST convention


def _add_column(ctx: _Context, table_name: str, col_name: str, col_type: str):
    """Add a column to a DB table if it doesn't already exist."""
    for table in ctx.schemas['db_schema'].get('tables', []):
        if table['name'] == table_name:
            existing = {c['name'] for c in table.get('columns', [])}
            if col_name not in existing:
                table.setdefault('columns', []).append({
                    'name': col_name, 'type': col_type,
                    'nullable': True, 'primary_key': False,
                    'unique': False, 'default': None
                })
            break


def _closest_path(target: str, candidates: set) -> str:
    """Return the candidate API path most similar to target (simple substring match)."""
    target_parts = set(target.strip('/').split('/'))
    best, best_score = '', 0
    for c in candidates:
        c_parts = set(c.strip('/').split('/'))
        score = len(target_parts & c_parts)
        if score > best_score:
            best, best_score = c, score
    return best if best_score > 0 else ''


def _to_snake(name: str) -> str:
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    s = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', s)
    return s.lower().replace(' ', '_')
