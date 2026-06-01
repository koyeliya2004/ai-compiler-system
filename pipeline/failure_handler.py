"""
Failure Handler
===============
Classifies and enriches prompts before Stage 1 processing.
Handles: vague, conflicting, underspecified, and clear prompts.
"""
import re

VAGUE_SIGNALS = [
    'app', 'website', 'platform', 'system', 'tool', 'thing',
    'something', 'make', 'build', 'create'
]

CONFLICT_SIGNALS = [
    ('free', 'paid'), ('public', 'private'), ('simple', 'complex'),
    ('no auth', 'login'), ('no login', 'auth')
]


def classify_prompt(prompt: str) -> tuple:
    """
    Returns (classification, issues, assumptions).
    classification: 'clear' | 'vague' | 'conflicting' | 'underspecified'
    """
    p = prompt.lower().strip()
    issues = []
    assumptions = []

    # Too short = underspecified
    if len(p.split()) < 5:
        issues.append('Prompt is very short. Please describe features, users, and purpose.')
        assumptions.append('Assuming a basic web application with standard authentication.')
        return 'underspecified', issues, assumptions

    # Check for conflicting signals
    for a, b in CONFLICT_SIGNALS:
        if a in p and b in p:
            issues.append(f"Conflicting requirements detected: '{a}' vs '{b}'. Resolving with reasonable defaults.")

    # Check for vague-only prompts (no specific features mentioned)
    has_features = any(w in p for w in [
        'login', 'auth', 'dashboard', 'payment', 'report', 'user',
        'admin', 'api', 'search', 'upload', 'email', 'notification',
        'profile', 'cart', 'order', 'analytics', 'role', 'permission'
    ])
    if not has_features:
        issues.append('No specific features detected. Inferring common features for this app type.')
        assumptions.append('Adding standard features: authentication, dashboard, user management.')

    # Make reasonable assumptions for missing info
    if 'payment' in p or 'paid' in p or 'premium' in p or 'stripe' in p:
        assumptions.append('Payment integration assumed to use Stripe.')
    if 'auth' in p or 'login' in p or 'user' in p:
        assumptions.append('Authentication assumed to use JWT tokens.')
    if 'admin' in p:
        assumptions.append('Admin role assumed to have full read/write/delete permissions.')

    if issues:
        return 'conflicting' if any('Conflicting' in i for i in issues) else 'vague', issues, assumptions

    return 'clear', issues, assumptions


def enrich_prompt(prompt: str, assumptions: list) -> str:
    """Append assumptions context to the prompt for the LLM."""
    if not assumptions:
        return prompt
    assumption_text = ' '.join(assumptions)
    return f"{prompt}\n\n[System assumptions: {assumption_text}]"
