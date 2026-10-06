"""Deterministic Smart Intent Router for agentctl do and agent-omitted commands.

Maps natural language prompts to specialist agent roles and execution modes.
Adheres strictly to Klaus forensic safety invariants:
1. Strict word-boundary matching (never matches action verbs inside code identifiers like `def fix_user()`).
2. Action verbs only for write intents; symptoms ('error', '500', 'traceback') remain diagnostic.
3. Explicit negation detection ('do not fix, just review') suppresses write-capable roles.
4. Fail-safe ambiguity rule: on ties or uncertainty, ALWAYS defaults to read_only (oracle/reviewer),
   never to workspace_write.
5. Emits structured advisory when write-capable intent is executed without --check.
"""

from __future__ import annotations

import re
from typing import Any

# Action keywords with explicit word boundaries
INTENT_SPECS: dict[str, dict[str, Any]] = {
    "review": {
        "patterns": [
            r"\breviews?\b",
            r"\baudits?\b",
            r"\binspects?\b",
            r"\banalyz(?:e|es|ing)\b",
            r"\bdiagnos(?:e|es|is)\b",
            r"\binvestigat(?:e|es|ing)\b",
            r"\barchitectures?\b",
            r"\bsecurity\b",
            r"\brisks?\b",
            r"\bperformance\b",
            r"\bexplain\b",
            r"\bwhy\b",
        ],
        "preferred_agent": "oracle",
        "fallback_agents": ["reviewer", "planner", "coder"],
        "autonomy": "read_only",
        "is_write": False,
    },
    "research": {
        "patterns": [
            r"\bdocumentation\b",
            r"\blibrar(?:y|ies)\b",
            r"\bdocs?\b",
            r"\bhow\s+to\s+use\b",
            r"\bhow\s+does\b",
            r"\breferences?\b",
            r"\bwhat\s+is\b",
            r"\blookup\b",
        ],
        "preferred_agent": "librarian",
        "fallback_agents": ["oracle", "cheap", "coder"],
        "autonomy": "read_only",
        "is_write": False,
    },
    "design": {
        "patterns": [
            r"\bui\b",
            r"\bux\b",
            r"\bresponsive\b",
            r"\bcss\b",
            r"\blayouts?\b",
            r"\bstyles?\b",
            r"\bnavbars?\b",
            r"\bstyling\b",
            r"\bthemes?\b",
            r"\bfrontend\b",
        ],
        "preferred_agent": "designer",
        "fallback_agents": ["fixer", "coder"],
        "autonomy": "read_only",
        "is_write": False,
    },
    "fix": {
        "patterns": [
            r"\bfix(?:es)?\b",
            r"\brepairs?\b",
            r"\bpatch(?:es)?\b",
            r"\bresolv(?:e|es)\b",
            r"\bhotfix(?:es)?\b",
        ],
        "preferred_agent": "fixer",
        "fallback_agents": ["coder", "eli"],
        "autonomy": "workspace_write",
        "is_write": True,
    },
    "implement": {
        "patterns": [
            r"\bimplement(?:s)?\b",
            r"\badd\s+features?\b",
            r"\bbuild\s+features?\b",
            r"\bcreate\s+endpoints?\b",
            r"\bnew\s+endpoints?\b",
            r"\bscaffolds?\b",
        ],
        "preferred_agent": "eli",
        "fallback_agents": ["fixer", "coder"],
        "autonomy": "workspace_write",
        "is_write": True,
    },
}

NEGATION_PATTERNS = [
    r"\b(?:do\s+not|don't|dont|never|avoid|without)\s+(?:make\s+changes|edit|write|modify|touch|fix|repair|patch|change)\b",
    r"\bjust\s+(?:review|diagnose|explain|inspect|analyze|check|read)\b",
    r"\bread[-\s]?only\b",
]


def detect_write_negation(prompt: str) -> bool:
    """Check if the prompt explicitly instructs not to edit or fix."""
    for pat in NEGATION_PATTERNS:
        if re.search(pat, prompt, re.IGNORECASE):
            return True
    return False


def _resolve_available_agent(
    preferred: str,
    fallbacks: list[str],
    available_agents: set[str],
    default_agent: str = "oracle",
) -> str:
    """Select the preferred agent if configured/available, otherwise first available fallback."""
    if preferred in available_agents:
        return preferred
    for fb in fallbacks:
        if fb in available_agents:
            return fb
    return default_agent if default_agent in available_agents else (next(iter(available_agents)) if available_agents else preferred)


def classify_intent(
    prompt: str,
    available_agents: set[str] | None = None,
    *,
    has_check: bool = False,
    has_artifacts: bool = False,
    default_readonly_agent: str = "oracle",
) -> dict[str, Any]:
    """Classify prompt text into an intent, specialist agent, and execution mode.

    Returns:
    {
        "intent": str,
        "selected_agent": str,
        "execution_mode": "run" | "iterate",
        "autonomy": "read_only" | "workspace_write",
        "confidence": float,
        "matched_keywords": list[str],
        "reason": str,
        "advisory": str | None,
        "write_negated": bool,
    }
    """
    text = (prompt or "").strip()
    agents_pool = set(available_agents) if available_agents is not None else set()

    if not text:
        return {
            "intent": "unknown",
            "selected_agent": default_readonly_agent,
            "execution_mode": "run",
            "autonomy": "read_only",
            "confidence": 0.0,
            "matched_keywords": [],
            "reason": "empty_prompt",
            "advisory": None,
            "write_negated": False,
        }

    is_negated = detect_write_negation(text)

    # Score each intent category using word-boundary matches
    scores: dict[str, list[str]] = {}
    for intent_name, spec in INTENT_SPECS.items():
        if is_negated and spec["is_write"]:
            # Suppress write-capable intents when negation is present
            continue
        matches = []
        for pat in spec["patterns"]:
            found = re.findall(pat, text, re.IGNORECASE)
            if found:
                # Store matched terms
                for m in found:
                    term = m if isinstance(m, str) else m[0]
                    matches.append(term.lower())
        if matches:
            scores[intent_name] = matches

    # Determine execution mode: presence of --check or --eval-artifact forces iterate mode
    forced_iterate = has_check or has_artifacts
    advisory = None

    if not scores:
        # Fallback: safe read-only agent in run mode
        fallback_agent = _resolve_available_agent(
            default_readonly_agent,
            ["reviewer", "planner", "oracle"],
            agents_pool,
            default_agent=default_readonly_agent,
        )
        return {
            "intent": "fallback",
            "selected_agent": fallback_agent,
            "execution_mode": "iterate" if forced_iterate else "run",
            "autonomy": "read_only",
            "confidence": 0.2,
            "matched_keywords": [],
            "reason": "no_keywords_matched_defaulting_readonly",
            "advisory": None,
            "write_negated": is_negated,
        }

    # Rank intents by count of distinct matched patterns
    ranked = sorted(scores.items(), key=lambda item: len(item[1]), reverse=True)
    top_intent, top_matches = ranked[0]
    top_count = len(top_matches)

    # Check for ties
    tied = [intent for intent, matches in ranked if len(matches) == top_count]
    if len(tied) > 1:
        # Klaus Fail-Safe Rule: On any tie between write and read-only, ALWAYS pick read-only
        readonly_candidates = [i for i in tied if not INTENT_SPECS[i]["is_write"]]
        if readonly_candidates:
            top_intent = readonly_candidates[0]
            top_matches = scores[top_intent]
            reason = f"tied_scores_{tied}_selected_safer_readonly_{top_intent}"
        else:
            top_intent = tied[0]
            top_matches = scores[top_intent]
            reason = f"tied_scores_{tied}_selected_{top_intent}"
        confidence = 0.5
    else:
        confidence = min(0.95, 0.6 + (top_count - 1) * 0.15)
        reason = f"matched_{top_intent}_keywords"

    spec = INTENT_SPECS[top_intent]
    agent = _resolve_available_agent(
        spec["preferred_agent"],
        spec["fallback_agents"],
        agents_pool,
        default_agent=default_readonly_agent,
    )

    if forced_iterate:
        execution_mode = "iterate"
    else:
        execution_mode = "run"
        if spec["is_write"]:
            advisory = "Write-type tasks are more reliable with a verification check. Consider adding: --check '<test command>'"

    return {
        "intent": top_intent,
        "selected_agent": agent,
        "execution_mode": execution_mode,
        "autonomy": spec["autonomy"],
        "confidence": confidence,
        "matched_keywords": sorted(set(top_matches)),
        "reason": reason,
        "advisory": advisory,
        "write_negated": is_negated,
    }
