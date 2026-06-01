"""
Evaluation Runner
==================
Runs 10 real + 10 edge case prompts through the pipeline.
Tracks: success rate, retries, failure types, latency.

Usage:
  python evaluation/run_evaluation.py              # dry run (no API key)
  python evaluation/run_evaluation.py --live       # real LLM calls
"""

import json
import time
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def dry_run_report():
    """Print test prompt list and expected behavior without LLM calls."""
    with open(ROOT / 'evaluation' / 'test_prompts.json') as f:
        data = json.load(f)

    print('\n' + '='*60)
    print('AI COMPILER SYSTEM — EVALUATION FRAMEWORK')
    print('='*60)

    total = 0
    for category, prompts in data.items():
        print(f'\n[{category.upper()}] ({len(prompts)} prompts)')
        for i, p in enumerate(prompts, 1):
            print(f'  {i:2}. {p["prompt"][:70]}...' if len(p['prompt']) > 70 else f'  {i:2}. {p["prompt"]}')
            print(f'       Expected: {p.get("expected_behavior", "success")}')
            total += 1

    print(f'\nTotal prompts: {total}')
    print('Run with --live flag + GROQ_API_KEY to execute real evaluation.')
    print('='*60)


def live_run():
    """Run real LLM evaluation and track metrics."""
    sys.path.insert(0, str(ROOT))
    from pipeline.stage1_intent_extraction import extract_intent

    with open(ROOT / 'evaluation' / 'test_prompts.json') as f:
        data = json.load(f)

    results = []
    success = 0
    total = 0
    total_retries = 0
    failure_types = {}

    all_prompts = []
    for category, prompts in data.items():
        for p in prompts:
            all_prompts.append((category, p))

    print(f'\nRunning {len(all_prompts)} prompts...\n')

    for category, item in all_prompts:
        total += 1
        prompt = item['prompt']
        t = time.time()
        try:
            result = extract_intent(prompt)
            latency = round((time.time() - t) * 1000, 2)
            success += 1
            results.append({
                'category': category,
                'prompt': prompt[:60],
                'status': 'success',
                'latency_ms': latency,
                'assumptions': len(result.get('assumptions', [])),
                'clarifications': len(result.get('clarifications_needed', []))
            })
            print(f'  ✓ [{category}] {prompt[:50]}... ({latency}ms)')
        except Exception as e:
            latency = round((time.time() - t) * 1000, 2)
            err_type = type(e).__name__
            failure_types[err_type] = failure_types.get(err_type, 0) + 1
            results.append({
                'category': category,
                'prompt': prompt[:60],
                'status': 'failed',
                'error': str(e)[:100],
                'latency_ms': latency
            })
            print(f'  ✗ [{category}] {prompt[:50]}... ERROR: {e}')

    print('\n' + '='*60)
    print('EVALUATION RESULTS')
    print('='*60)
    print(f'Total prompts:    {total}')
    print(f'Success:          {success}/{total} ({round(success/total*100)}%)')
    print(f'Failures:         {total-success}')
    print(f'Failure types:    {failure_types}')
    avg_latency = sum(r['latency_ms'] for r in results) / len(results)
    print(f'Avg latency:      {round(avg_latency)}ms')
    print('='*60)

    out_file = ROOT / 'evaluation' / 'results.json'
    with open(out_file, 'w') as f:
        json.dump({'summary': {'total': total, 'success': success, 'failure_types': failure_types, 'avg_latency_ms': round(avg_latency)}, 'results': results}, f, indent=2)
    print(f'Results saved to: {out_file}')


if __name__ == '__main__':
    if '--live' in sys.argv:
        live_run()
    else:
        dry_run_report()
