"""AI Compiler System — Multi-Stage Generation Pipeline"""
# Lazy imports only — do NOT import at module level to avoid startup crashes
# All stages are imported inside their respective functions

__all__ = [
    'extract_intent',
    'design_system',
    'generate_schemas',
    'refine_schemas',
    'validate_pipeline_output',
    'repair_pipeline_output',
    'check_execution_readiness',
]
