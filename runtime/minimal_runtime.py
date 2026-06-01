"""
Runtime -- Minimal artifact generators
Exports:
  generate_openapi_stub(output) -> dict
  generate_db_migration_stub(output) -> str
"""
import json


def generate_openapi_stub(output: dict) -> dict:
    """Generate a minimal OpenAPI 3.0 stub from pipeline output."""
    try:
        schemas = output.get('schemas', {})
        if isinstance(schemas, dict) and 'repaired_schemas' in schemas:
            schemas = schemas['repaired_schemas']
        api_config = schemas.get('api_config', {})
        endpoints = api_config.get('endpoints', [])
        app_name = output.get('app_name', 'Generated App')
        base_path = api_config.get('base_path', '/api/v1')

        paths = {}
        for ep in endpoints:
            path = ep.get('path', '/unknown')
            method = ep.get('method', 'GET').lower()
            if path not in paths:
                paths[path] = {}
            paths[path][method] = {
                'summary': 'Auto-generated endpoint',
                'security': [{'bearerAuth': []}] if ep.get('auth_required') else [],
                'responses': {'200': {'description': 'Success'}}
            }

        return {
            'openapi': '3.0.0',
            'info': {'title': app_name, 'version': '1.0.0'},
            'servers': [{'url': base_path}],
            'paths': paths,
            'components': {
                'securitySchemes': {
                    'bearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}
                }
            }
        }
    except Exception:
        return {'openapi': '3.0.0', 'info': {'title': 'Generated App', 'version': '1.0.0'}, 'paths': {}}


def generate_db_migration_stub(output: dict) -> str:
    """Generate SQL CREATE TABLE statements from pipeline output."""
    try:
        schemas = output.get('schemas', {})
        if isinstance(schemas, dict) and 'repaired_schemas' in schemas:
            schemas = schemas['repaired_schemas']
        db_schema = schemas.get('db_schema', {})
        tables = db_schema.get('tables', [])
        dialect = db_schema.get('dialect', 'postgresql')

        lines = ['-- Auto-generated migration', '-- Dialect: ' + dialect, '']
        for table in tables:
            name = table.get('name', 'unknown')
            columns = table.get('columns', [])
            col_defs = []
            for col in columns:
                col_name = col.get('name', 'col')
                col_type = col.get('type', 'TEXT')
                nullable = '' if col.get('nullable', True) else ' NOT NULL'
                pk = ' PRIMARY KEY' if col.get('primary_key') else ''
                unique = ' UNIQUE' if col.get('unique') else ''
                default = (' DEFAULT ' + str(col['default'])) if col.get('default') is not None else ''
                col_defs.append('  ' + col_name + ' ' + col_type + pk + unique + nullable + default)

            fks = table.get('foreign_keys', [])
            for fk in fks:
                col = fk.get('column', '')
                ref = fk.get('references', '')
                if col and ref:
                    ref_table, ref_col = (ref.split('.') + ['id'])[:2]
                    col_defs.append(
                        '  FOREIGN KEY (' + col + ') REFERENCES ' + ref_table + '(' + ref_col + ')'
                    )

            lines.append('CREATE TABLE IF NOT EXISTS ' + name + ' (')
            lines.append(',\n'.join(col_defs))
            lines.append(');')
            lines.append('')

        return '\n'.join(lines)
    except Exception as e:
        return '-- Migration generation failed: ' + str(e)
