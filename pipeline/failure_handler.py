"""
Failure Handler
================
Handles vague, conflicting, and underspecified prompts.

Strategy:
- VAGUE: Make reasonable assumptions, document them, proceed
- CONFLICTING: Detect contradictions, ask for clarification OR
  apply a safe default resolution rule
- UNDERSPECIFIED: Fill in defaults, list all assumptions

This module is called by Stage 1 before the main LLM call.
"""

import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# Patterns that indicate vague input
VAGUE_PATTERNS = [
    r'^build (a |an )?app$',
    r'^make (a |an )?website$',
    r'^create something$',
    r'^i need (a |an )?platform$',
    r'.{0,30}$',  # very short (under 30 chars)
]

# Conflicting requirement pairs
CONFLICT_RULES = [
    (
        ['no login', 'no auth', 'no authentication', 'public app', 'no users'],
        ['role-based', 'admin', 'permissions', 'rbac', 'user roles'],
        'Conflict: public app vs role-based access. Assuming auth IS required since roles were specified.'
    ),
    (
        ['free', 'no payment', 'no subscription', 'open source'],
        ['premium', 'paid', 'subscription', 'stripe', 'payment'],
        'Conflict: free app vs payment features. Assuming freemium model: free tier + optional premium.'
    ),
    (
        ['simple', 'basic', 'minimal', 'lightweight'],
        ['enterprise', 'complex', 'advanced', 'full-featured', 'scalable'],
        'Conflict: simple vs complex. Proceeding with MVP scope — core features only.'
    ),
]


def classify_prompt(prompt: str) -> Tuple[str, list, list]:
    """
    Classify a prompt and return:
    - classification: 'clear' | 'vague' | 'conflicting' | 'underspecified'
    - issues: list of detected problems
    - assumptions: list of assumptions made to proceed
    """
    p = prompt.lower().strip()
    issues = []
    assumptions = []

    # Check vague
    is_vague = len(prompt.strip()) < 30 or any(
        re.match(pattern, p) for pattern in VAGUE_PATTERNS[:4]
    )
    if is_vague:
        issues.append('Prompt is too vague or short.')
        assumptions += [
            'Assuming a web application with user authentication.',
            'Assuming admin and user roles.',
            'Assuming a dashboard as the main page.',
            'Assuming PostgreSQL as the database.',
        ]

    # Check conflicts
    for neg_terms, pos_terms, resolution in CONFLICT_RULES:
        has_neg = any(t in p for t in neg_terms)
        has_pos = any(t in p for t in pos_terms)
        if has_neg and has_pos:
            issues.append(f'Conflicting requirements detected: {neg_terms[0]} vs {pos_terms[0]}')
            assumptions.append(resolution)

    # Check underspecified (no entities or features mentioned)
    feature_keywords = ['login', 'dashboard', 'list', 'form', 'report', 'chart',
                        'upload', 'search', 'filter', 'payment', 'email', 'notification']
    has_features = any(kw in p for kw in feature_keywords)
    if not has_features and not is_vague:
        issues.append('No specific features mentioned.')
        assumptions.append('Assuming standard CRUD features: list, create, edit, delete.')
        assumptions.append('Assuming email/password authentication.')

    if not issues:
        classification = 'clear'
    elif any('Conflict' in i for i in issues):
        classification = 'conflicting'
    elif is_vague:
        classification = 'vague'
    else:
        classification = 'underspecified'

    return classification, issues, assumptions


def enrich_prompt(prompt: str, assumptions: list) -> str:
    """
    Enrich a vague/underspecified prompt with assumptions
    so the LLM has enough context to generate a valid schema.
    """
    if not assumptions:
        return prompt
    assumption_str = ' '.join(assumptions)
    return f"{prompt}\n\n[System assumptions: {assumption_str}]"


def needs_clarification(classification: str, issues: list) -> bool:
    """
    Returns True if the prompt is so vague that clarification
    should be requested rather than assumed.
    Only triggered for extremely short prompts (< 10 chars).
    """
    return classification == 'vague' and len(issues) > 0 and len(issues[0]) < 10


if __name__ == '__main__':
    tests = [
        'Build an app',
        'Build a CRM with login, contacts, dashboard, role-based access, and premium payments.',
        'Free open source tool with admin roles and stripe payments',
        'Simple basic app with enterprise-grade scalability',
        'Create a platform',
    ]
    for t in tests:
        cls, issues, assumptions = classify_prompt(t)
        print(f'\nPrompt: {t[:60]}')
        print(f'  Classification: {cls}')
        print(f'  Issues: {issues}')
        print(f'  Assumptions: {assumptions}')
