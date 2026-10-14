import re
from pathlib import Path

from runtime_agents.models import PolicyDecision


TRANSIENT_MARKERS = (
    "429 too many requests",
    "http 429",
    "http 503",
    "503 service unavailable",
    "service unavailable",
    "model_cooldown",
    "resource_exhausted",
    "too many requests",
    "temporarily unavailable",
    "rate limit",
    "gateway unavailable",
    "connection reset",
    "resource exhausted",
    "resource has been exhausted",
    "cooling down",
    "all credentials for model",
    "unexpected server error",
    "internal server error",
    '"name": "unknownerror"',
    "insufficient_quota",
    "quota exceeded",
    "plan quota exceeded",
    "quota_exhausted",
)

CAPABILITY_PATTERNS = {
    "workspace_write": [],
    "git_push": ["push", "git push"],
    "deploy": ["deploy"],
    "secrets": ["api key", "secret", "password", ".env", "credentials"],
    "global_config": ["~/.config", str(Path.home() / ".config"), "~/.ssh", str(Path.home() / ".ssh"), "~/.bashrc", "~/.zshrc", "global config"],
    "destructive_delete": ["rm -rf /", "rm -rf ~", "find * -delete", "delete everything"],
    "global_install": ["npm install -g", "pip install --user", "sudo apt install", "brew install", "global install"],
    "broker_order_submit": [],
    "options_autotrade": [],
    "margin": [],
    "external_purchase": [],
    "checkout": [],
    "payment": [],
    "captcha_bypass": [],
}


def known_capabilities() -> set[str]:
    return set(CAPABILITY_PATTERNS.keys())


_NEGATION = re.compile(r"\b(?:do\s+not|don't|never|not)\b", re.IGNORECASE)
# These words start a new directive. An earlier prohibition must not cover it,
# and a second prohibition must not cancel the first by parity.
_SCOPE_RESET = re.compile(r"\b(?:but|then|however|and)\b", re.IGNORECASE)
_PLEASE = re.compile(r"\bplease\b", re.IGNORECASE)
_LINE_CONTINUATION = re.compile(r"(?:^|\s)(?:or|nor)\s*$", re.IGNORECASE)


def _capability_needles() -> tuple[str, ...]:
    needles = {
        pattern.lower().strip()
        for patterns in CAPABILITY_PATTERNS.values()
        for pattern in patterns
        if pattern and pattern.strip()
    }
    return tuple(sorted(needles, key=len, reverse=True))


def _contains_capability(text: str) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in _capability_needles())


def _negation_suppresses(span: str) -> bool:
    matches = list(_NEGATION.finditer(span))
    if not matches:
        return False
    start = len(matches) - 1
    while start > 0 and not span[matches[start - 1].end():matches[start].start()].strip():
        start -= 1
    stack = matches[start:]
    # Adjacent wording such as "not not" is ambiguous, so it does not suppress.
    if len(stack) >= 2 and not span[stack[-1].end():].strip():
        return len(stack) % 2 == 1
    return True


def _newline_directive_ends(clause: str) -> list[int]:
    """Return a reset when the capability being tested starts a new line.

    The clause excludes that capability, so a line-initial mention leaves the
    clause ending at the newline. List continuations stay in the prohibition.
    A new line is a new instruction only when the previous line already names a
    capability after its negation. "do not ever\\npush" stays negative;
    "do not deploy\\npush the branch" does not.
    """
    stripped = clause.rstrip(" \t\r")
    if not stripped.endswith("\n"):
        return []
    newline = stripped.rfind("\n")
    before = stripped[:newline].rstrip(" \t\r")
    if clause[newline + 1:].strip():
        return []
    if before.endswith(",") or _LINE_CONTINUATION.search(before):
        return []
    if not _contains_capability(before):
        return []
    negations = list(_NEGATION.finditer(before))
    if negations and not re.search(r"\w", before[negations[-1].end():]):
        return []
    return [len(clause)]


def _please_directive_ends(clause: str) -> list[int]:
    """Return ends of imperative cues that begin a new directive.

    "please" immediately after a negation is still that prohibition, as in
    "do not please push". After another word, including across a comma, it
    starts a separate instruction.
    """
    ends = []
    for match in _PLEASE.finditer(clause):
        negations = list(_NEGATION.finditer(clause[:match.start()]))
        if negations and not re.search(r"\w", clause[negations[-1].end():match.start()]):
            continue
        ends.append(match.end())
    return ends


def _mention_negated(haystack: str, index: int) -> bool:
    prefix = haystack[:index]
    boundary = max(prefix.rfind(mark) for mark in ".!;")
    clause = prefix[boundary + 1:]
    reset_end = 0
    found = False
    for match in _SCOPE_RESET.finditer(clause):
        reset_end = match.end()
        found = True
    for end in (*_newline_directive_ends(clause), *_please_directive_ends(clause)):
        if end >= reset_end:
            reset_end = end
            found = True
    span = clause[reset_end:] if found else clause
    return _negation_suppresses(span)


def _pattern_requested(haystack: str, pattern: str, *, known: bool) -> bool:
    needle = pattern.lower()
    if not needle:
        return False
    indexes = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            break
        indexes.append(index)
        start = index + len(needle)
    if not indexes:
        return False
    negated = [_mention_negated(haystack, index) for index in indexes]
    if any(not item for item in negated):
        return True
    return not known


def detect_capabilities(text: str, allowed: list[str] | None = None, patterns: dict | None = None) -> list[str]:
    haystack = (text or "").lower()
    pattern_map = patterns or CAPABILITY_PATTERNS
    candidates = allowed or list(pattern_map.keys())
    hits = []
    for cap in candidates:
        for p in pattern_map.get(cap, []):
            if _pattern_requested(haystack, p, known=patterns is None):
                hits.append(cap)
                break
    return sorted(set(hits))


def evaluate_approval(text: str, approved_caps: list[str] | None, mode: str, required_caps: list[str] | None = None, patterns: dict | None = None) -> PolicyDecision:
    required = required_caps or []
    matched = detect_capabilities(text, allowed=required, patterns=patterns)
    approved = sorted(set(approved_caps or []))
    blocked = [c for c in matched if c not in approved]
    return PolicyDecision(mode=mode, capabilities=matched, approved=approved, blocked=blocked)


def classify_failure(stdout: str, stderr: str, returncode: int) -> str | None:
    if returncode == 0:
        return None
    # Check stderr for gateway/infrastructure errors
    err_text = (stderr or "").lower()
    if any(marker.lower() in err_text for marker in TRANSIENT_MARKERS):
        return "transient_model_error"
    # For stdout, check specific multi-word error markers so bare numbers don't match test assertions
    out_text = (stdout or "").lower()
    out_markers = (
        "429 too many requests",
        "http 429",
        "http 503",
        "503 service unavailable",
        "service unavailable",
        "rate limit",
        "rate_limit_exceeded",
        "model_cooldown",
        "insufficient_quota",
        "quota exceeded",
        "plan quota exceeded",
        "quota_exhausted",
        "all credentials for model",
    )
    if any(m in out_text for m in out_markers):
        return "transient_model_error"
    return None


def compute_backoff_delay(attempt: int, stderr: str = "", base_delay: float = 1.0, max_delay: float = 30.0) -> float:
    """Compute bounded exponential backoff delay in seconds for transient errors."""
    import re
    match = re.search(r'(?:retry-after|retry after)[:\s]+(\d+)', stderr or "", re.IGNORECASE)
    if match:
        try:
            return min(float(match.group(1)), max_delay)
        except ValueError:
            pass
    delay = base_delay * (2 ** max(0, attempt - 1))
    import random
    jitter = random.uniform(0.05, 0.25)
    return min(delay + jitter, max_delay)
