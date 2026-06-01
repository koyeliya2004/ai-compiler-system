"""
Minimal Runtime Simulator
==========================
Simulates a runtime that consumes the AI Compiler output and
"boots" a minimal application from the generated configs.

This proves execution awareness: the output is directly usable.

In production, replace with a real code generator or
framework adapter (e.g., Next.js scaffolding, FastAPI generator).
"""

import json
from typing import Dict, Any


def simulate_runtime(final_output: Dict[str, Any]) -> Dict[str, Any]:
    """Boot simulation — delegates to Stage 6 execution readiness check."""
    from pipeline.stage6_execution import check_execution_readiness
    return check_execution_readiness(final_output)


def generate_openapi_stub(final_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a minimal OpenAPI 3.0 stub from the API config.
    Proves the output can power a real API spec without manual editing.
    """
    api = final_output.get('schemas', {}).get('api_config', {})
    endpoints = api.get('endpoints', [])
    app_name = final_output.get('app_name', 'Generated App')

    paths = {}
    for ep in endpoints:
        path = ep.get('path', '')
        method = ep.get('method', 'GET').lower()
        paths.setdefault(path, {})[method] = {
            'summary': ep.get('description', ''),
            'security': [{'BearerAuth': []}] if ep.get('auth_required') else [],
            'responses': {'200': {'description': 'Success'}}
        }

    return {
        'openapi': '3.0.0',
        'info': {'title': app_name, 'version': '0.1.0'},
        'paths': paths,
        'components': {
            'securitySchemes': {
                'BearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}
            }
        }
    }


def generate_db_migration_stub(final_output: Dict[str, Any]) -> str:
    """
    Generate a minimal SQL migration script from DB schema.
    Proves the output can drive a real DB without manual editing.
    """
    tables = final_output.get('schemas', {}).get('db_schema', {}).get('tables', [])
    lines = [
        '-- Auto-generated migration from AI Compiler output',
        '-- Run with: psql -U user -d dbname -f migration.sql',
        ''
    ]

    for table in tables:
        ddl = table.get('ddl')
        if ddl:
            lines.append(ddl)
            lines.append('')
        else:
            cols = []
            for col in table.get('columns', []):
                parts = [col['name'], col.get('type', 'TEXT')]
                if col.get('primary_key'):
                    parts.append('PRIMARY KEY')
                if not col.get('nullable', True):
                    parts.append('NOT NULL')
                if col.get('unique') and not col.get('primary_key'):
                    parts.append('UNIQUE')
                if col.get('default'):
                    parts.append(f"DEFAULT {col['default']}")
                cols.append('  ' + ' '.join(parts))
            lines.append(f"CREATE TABLE IF NOT EXISTS {table['name']} (")
            lines.append(',\n'.join(cols))
            lines.append(');')
            lines.append('')

    return '\n'.join(lines)


if __name__ == '__main__':
    print(json.dumps({
        'message': 'Runtime simulator ready.',
        'functions': ['simulate_runtime()', 'generate_openapi_stub()', 'generate_db_migration_stub()']
    }, indent=2))
