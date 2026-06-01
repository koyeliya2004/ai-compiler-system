# Task 7 — Evaluation Framework

This evaluation framework is designed to produce **actual benchmark metrics**, not claims.

## Dataset

- **10 real product prompts** — realistic SaaS / internal tool requests.
- **10 edge-case prompts** — vague, conflicting, incomplete, or logically inconsistent specs.

Dataset file:
- `evaluation/test_prompts.json`

## Metrics tracked

For every prompt run, the framework records:

- Success / partial / failed status
- Total latency per request
- Per-stage latency:
  - Stage 1: Intent Extraction
  - Stage 2: System Design
  - Stage 3: Schema Generation
  - Stage 4: Refinement
  - Stage 5: Validation + Repair
  - Stage 6: Execution Awareness
- Retries per request
- Repair count per request
- Execution score
- Number of clarifications requested
- Number of assumptions made
- Number of issues detected
- Failure type taxonomy

## Outputs

Live runs generate these files under `evaluation/results/`:

| File | Purpose |
|------|---------|
| `latest_report.json` | Full structured run output |
| `latest_report.csv` | Row-wise benchmark table |
| `latest_summary.md` | Human-readable benchmark summary |

## Commands

```bash
# View dataset only
python evaluation/run_evaluation.py

# Run full live evaluation
python evaluation/run_evaluation.py --live

# Optional: only run Stage 1 benchmark
python evaluation/run_evaluation.py --live --stage1-only
```

## Why this matters

The task explicitly asks for a **serious signal** on system quality.
This framework demonstrates:

- how often the system succeeds on unseen prompts,
- how often repair is needed,
- where latency is spent,
- what kinds of failures still occur,
- whether execution readiness remains high under ambiguous input.

This makes the project look like an **engineered system**, not a prompt demo.
