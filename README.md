# 🤖 AI Compiler System

> Natural language → structured config → validated → executable → working application

A compiler-inspired pipeline that converts open-ended user instructions into strict, validated, executable app configurations.

**Reference:** [base44.com](https://base44.com/)

---

## 🏗️ Architecture Overview

```
User Prompt
    │
    ▼
┌─────────────────────────────────────┐
│  Stage 1: Intent Extraction         │  Parse → IntentSchema
│  Stage 2: System Design Layer       │  Architecture → AppBlueprint
│  Stage 3: Schema Generation         │  UI + API + DB + Auth configs
│  Stage 4: Refinement Layer          │  Cross-layer consistency check
│  Stage 5: Validation + Repair       │  Detect & fix issues
│  Stage 6: Execution Awareness       │  Runtime-ready output
└─────────────────────────────────────┘
    │
    ▼
Executable App Config (JSON)
```

---

## 📁 Project Structure

```
ai-compiler-system/
├── pipeline/
│   ├── stage1_intent_extraction.py   # Stage 1: Parse user intent
│   ├── stage2_system_design.py       # Stage 2: App architecture
│   ├── stage3_schema_generation.py   # Stage 3: UI/API/DB/Auth schemas
│   ├── stage4_refinement.py          # Stage 4: Cross-layer consistency
│   ├── stage5_validation_repair.py   # Stage 5: Validate & auto-repair
│   └── stage6_execution.py           # Stage 6: Execution-ready output
├── schemas/
│   ├── intent_schema.json            # IntentSchema contract
│   ├── app_blueprint_schema.json     # AppBlueprint contract
│   └── output_schema.json            # Final output contract
├── evaluation/
│   ├── test_prompts.json             # 10 real + 10 edge case prompts
│   └── run_evaluation.py             # Evaluation harness
├── runtime/
│   └── minimal_runtime.py            # Basic app runtime simulator
├── api/
│   └── app.py                        # FastAPI web interface
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 Stages

| Stage | Name | Input | Output |
|-------|------|-------|--------|
| 1 | Intent Extraction | Raw user prompt | `IntentSchema` JSON |
| 2 | System Design | `IntentSchema` | `AppBlueprint` JSON |
| 3 | Schema Generation | `AppBlueprint` | UI + API + DB + Auth configs |
| 4 | Refinement | All configs | Resolved, consistent configs |
| 5 | Validation + Repair | Configs | Validated/repaired configs |
| 6 | Execution | Final configs | Runtime-ready app spec |

---

## ⚡ Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Add your OPENAI_API_KEY to .env

# Run the pipeline
python pipeline/stage1_intent_extraction.py

# Start the web API
uvicorn api.app:app --reload
```

---

## 📊 Evaluation Metrics

| Metric | Target |
|--------|--------|
| Success Rate | > 90% |
| Avg Retries | < 2 |
| Avg Latency | < 15s |
| JSON Validity | 100% |

---

## 🧪 Test Prompts

See `evaluation/test_prompts.json` for 10 real product prompts + 10 edge cases (vague, conflicting, incomplete).
