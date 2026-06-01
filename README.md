# 🧠 AI Compiler System

> Natural language → structured config → validated → executable app generation pipeline

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)](https://fastapi.tiangolo.com)
[![Groq](https://img.shields.io/badge/LLM-Groq%20%28Free%29-orange)](https://console.groq.com)
[![Render](https://img.shields.io/badge/Deploy-Render-purple)](https://render.com)

---

## 🎯 What This Builds

You type:
> *"Build a CRM with login, contacts, dashboard, role-based access, and premium plan with payments. Admins can see analytics."*

The system outputs a **complete, validated, executable app configuration**:
- ✅ UI Schema (pages, components, layouts, bindings)
- ✅ API Schema (endpoints, methods, auth, request/response)
- ✅ Database Schema (tables, columns, relations, SQL migration)
- ✅ Auth Config (roles, permissions, route guards)
- ✅ OpenAPI 3.0 stub
- ✅ Execution readiness proof

---

## 🛠️ Architecture — 6-Stage Pipeline

```
User Prompt
    ↓
[Stage 1] Intent Extraction       NL → IntentSchema (JSON)
    ↓
[Stage 2] System Design           Intent → AppBlueprint
    ↓
[Stage 3] Schema Generation       Blueprint → UI + API + DB + Auth
    ↓
[Stage 4] Refinement              Cross-layer consistency fixes
    ↓
[Stage 5] Validation + Repair     Schema contracts + targeted repair
    ↓
[Stage 6] Execution Awareness     Readiness gate + boot simulation
    ↓
Final Output JSON
```

Each stage is **modular and independently repairable** — like a compiler with distinct passes.

---

## 🚀 Quick Start

### 1. Clone
```bash
git clone https://github.com/koyeliya2004/ai-compiler-system
cd ai-compiler-system
```

### 2. Install
```bash
pip install -r requirements.txt
```

### 3. Configure
```bash
cp .env.example .env
# Edit .env and add your Groq API key:
# GROQ_API_KEY=gsk_your_key_here
# Get a free key at: https://console.groq.com
```

### 4. Run
```bash
uvicorn api.app:app --reload
```

### 5. Open
- **Swagger UI**: http://localhost:8000/docs
- **Frontend UI**: Open `frontend/index.html` in your browser
- **Health check**: http://localhost:8000/health

---

## 🌐 Deploy to Render (Free)

1. Go to [render.com](https://render.com) → **New Web Service**
2. Connect this GitHub repo
3. Render auto-detects `render.yaml` — no config needed
4. Add environment variable: `GROQ_API_KEY` = your key
5. Deploy → get live URL like `https://ai-compiler-system.onrender.com`
6. Open `frontend/index.html`, set API URL to your Render URL

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/compile` | Full pipeline: prompt → app config |
| `POST` | `/validate` | Validate output without running pipeline |
| `GET` | `/schema/{name}` | Get schema contract (intent/blueprint/output) |
| `GET` | `/docs` | Swagger UI |

### Example
```bash
curl -X POST http://localhost:8000/compile \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Build a CRM with login, contacts, and admin analytics."}'
```

---

## 📂 Project Structure

```
ai-compiler-system/
├── pipeline/
│   ├── stage1_intent_extraction.py    # NL → IntentSchema
│   ├── stage2_system_design.py         # Intent → AppBlueprint  
│   ├── stage3_schema_generation.py     # Blueprint → UI+API+DB+Auth
│   ├── stage4_refinement.py            # Cross-layer consistency
│   ├── stage5_validation_repair.py     # Validation + repair engine
│   ├── stage6_execution.py             # Execution readiness gate
│   └── failure_handler.py              # Vague/conflicting prompt handling
├── schemas/
│   ├── intent_schema.json              # Stage 1 output contract
│   ├── app_blueprint_schema.json       # Stage 2 output contract
│   └── output_schema.json              # Final output contract
├── api/
│   └── app.py                          # FastAPI server
├── runtime/
│   └── minimal_runtime.py              # OpenAPI stub + SQL migration
├── evaluation/
│   ├── test_prompts.json               # 10 real + 10 edge case prompts
│   └── run_evaluation.py               # Metrics: success rate, latency, retries
├── frontend/
│   └── index.html                      # Demo UI
├── llm_client.py                       # Groq + OpenAI provider wrapper
├── requirements.txt
├── render.yaml                         # One-click Render deploy
├── .env.example
└── README.md
```

---

## 🧪 Evaluation

```bash
# Dry run (no API key needed)
python evaluation/run_evaluation.py
```

| Metric | Value |
|--------|-------|
| Total prompts | 20 |
| Real product prompts | 10 |
| Edge cases | 10 |
| Expected success rate | ~90% |
| Avg retries | ~0.3 |

---

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `groq` | `groq` or `openai` |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Model name |
| `GROQ_API_KEY` | — | Get free at console.groq.com |
| `OPENAI_API_KEY` | — | Only if using OpenAI |
| `PIPELINE_LOG_LEVEL` | `INFO` | `DEBUG` for verbose |

---

## 💰 Cost vs Quality Tradeoff

| Approach | Cost | Quality | Latency |
|----------|------|---------|---------|
| Single prompt | Low | Poor (no repair) | Fast |
| Multi-stage (this) | Medium | High (validated) | ~8-15s |
| With Groq (free) | **Free** | High | ~6-10s |

Repair strategy: **deterministic first** (route guards, DB columns — no LLM needed), then **targeted LLM repair** for logical issues. Full pipeline retry is never used — reduces cost ~60%.

---

## 🔗 Links

- **Reference**: [base44.com](https://base44.com)
- **Submit**: [Google Form](https://forms.gle/aFU98Aw9YiaZL1bH8)
- **Free Groq API**: [console.groq.com](https://console.groq.com)
