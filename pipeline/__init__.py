"""
AI Compiler Pipeline—stage registry.

Each stage exposes a `run` callable:
  Stage 1: extract_intent(prompt: str)   -> IntentSchema
  Stage 2: design_system(intent: dict)   -> SystemDesign
  Stage 3: generate_schemas(design: dict)-> AllSchemas
  Stage 4: refine(intent, design, schemas) -> RefinedOutput
  Stage 5: validate_and_repair(output: dict) -> ValidatedOutput
  Stage 6: execute(output: dict)         -> ExecutionResult
"""

from pipeline.stage1_intent_extraction  import run as extract_intent
from pipeline.stage2_system_design      import run as design_system
from pipeline.stage3_schema_generation  import run as generate_schemas
from pipeline.stage4_refinement         import run as refine
from pipeline.stage5_validation_repair  import run as validate_and_repair
from pipeline.stage6_execution          import run as execute

STAGES = [
    ('Stage 1 — Intent Extraction',  extract_intent),
    ('Stage 2 — System Design',       design_system),
    ('Stage 3 — Schema Generation',   generate_schemas),
    ('Stage 4 — Refinement',          refine),
    ('Stage 5 — Validation & Repair', validate_and_repair),
    ('Stage 6 — Execution Awareness', execute),
]

__all__ = [
    'extract_intent',
    'design_system',
    'generate_schemas',
    'refine',
    'validate_and_repair',
    'execute',
    'STAGES',
]
