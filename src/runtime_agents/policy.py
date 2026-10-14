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
# List coordination only. A lead-in word is not special-cased by name.
_OR_GAP = re.compile(
    r"^[\s,]*(?:(?:or|nor)\b[\s,]*|[A-Za-z]+[\s]*,[\s]*)*(?:(?:or|nor)\b[\s,]*)?$",
    re.IGNORECASE,
)
_LIST_TAIL = re.compile(r"\s*(?:$|[.!;?]|[,]|or\b|nor\b)", re.IGNORECASE)


def _capability_needles() -> tuple[str, ...]:
    needles = {
        pattern.lower().strip()
        for patterns in CAPABILITY_PATTERNS.values()
        for pattern in patterns
        if pattern and pattern.strip()
    }
    return tuple(sorted(needles, key=len, reverse=True))


def _last_capability_end(text: str) -> int | None:
    lowered = text.lower()
    last_end = None
    for needle in _capability_needles():
        start = 0
        while True:
            found = lowered.find(needle, start)
            if found < 0:
                break
            end = found + len(needle)
            if last_end is None or end > last_end:
                last_end = end
            start = found + 1
    return last_end


def _suppressing_negation_end(span: str) -> int | None:
    matches = list(_NEGATION.finditer(span))
    if not matches:
        return None
    start = len(matches) - 1
    while start > 0 and not span[matches[start - 1].end():matches[start].start()].strip():
        start -= 1
    stack = matches[start:]
    # Adjacent wording such as "not not" is ambiguous, so an even stack does not suppress.
    if len(stack) >= 2 and not span[stack[-1].end():].strip() and len(stack) % 2 == 0:
        return None
    return stack[-1].end()


def _is_coordinated_continuation(gap: str, after_mention: str) -> bool:
    """A later capability stays prohibited only inside the same coordinated list.

    "or"/"nor" and comma-separated bare items continue the prohibition. A new
    line or other wording does not. A bare comma is a list only when this
    capability is a bare item or the list continues after it; otherwise the
    request stays gated.
    """
    if "\n" in gap and not re.search(r"(?:,|\bor\b|\bnor\b)", gap, re.IGNORECASE):
        return False
    if not _OR_GAP.fullmatch(gap):
        return False
    if re.search(r"\b(?:or|nor)\b", gap, re.IGNORECASE):
        return True
    return _LIST_TAIL.match(after_mention) is not None


def _mention_negated(haystack: str, index: int, mention_end: int) -> bool:
    prefix = haystack[:index]
    boundary = max(prefix.rfind(mark) for mark in ".!;")
    clause = prefix[boundary + 1:]
    negation_end = _suppressing_negation_end(clause)
    if negation_end is None:
        return False
    after_negation = clause[negation_end:]
    previous_end = _last_capability_end(after_negation)
    if previous_end is None:
        return True
    return _is_coordinated_continuation(after_negation[previous_end:], haystack[mention_end:])


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
    negated = [_mention_negated(haystack, index, index + len(needle)) for index in indexes]
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
