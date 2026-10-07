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


def detect_capabilities(text: str, allowed: list[str] | None = None, patterns: dict | None = None) -> list[str]:
    haystack = (text or "").lower()
    pattern_map = patterns or CAPABILITY_PATTERNS
    candidates = allowed or list(pattern_map.keys())
    hits = []
    for cap in candidates:
        for p in pattern_map.get(cap, []):
            if p.lower() in haystack:
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
