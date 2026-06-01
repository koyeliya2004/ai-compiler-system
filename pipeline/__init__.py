"""
AI Compiler Pipeline — stage registry

Each stage exposes a `run(input_dict) -> dict` interface.
The orchestrator (api/app.py) calls them in order:

  Stage 1: extract_intent      (NL prompt        -> IntentSchema)
  Stage 2: design_system       (IntentSchema      -> SystemDesign)
  Stage 3: generate_schemas    (SystemDesign      -> AllSchemas)
  Stage 4: refine              (AllSchemas        -> RefinedSchemas)
  Stage 5: validate_and_repair (RefinedSchemas    -> ValidatedOutput)
  Stage 6: check_execution     (ValidatedOutput   -> ExecutionReport)
"""

from pipeline.stage1_intent_extraction  import extract_intent,   run as run_stage1
from pipeline.stage2_system_design      import design_system,     run as run_stage2
from pipeline.stage3_schema_generation  import run                as run_stage3
from pipeline.stage4_refinement         import run                as run_stage4
from pipeline.stage5_validation_repair  import run                as run_stage5
from pipeline.stage6_execution          import run                as run_stage6

STAGE_RUNNERS = [
    run_stage1,
    run_stage2,
    run_stage3,
    run_stage4,
    run_stage5,
    run_stage6,
]

__all__ = [
    'extract_intent',
    'design_system',
    'run_stage1',
    'run_stage2',
    'run_stage3',
    'run_stage4',
    'run_stage5',
    'run_stage6',
    'STAGE_RUNNERS',
]
