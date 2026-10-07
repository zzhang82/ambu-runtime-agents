from pathlib import Path

from runtime_agents.models import PolicyDecision


TRANSIENT_MARKERS = (
    "429",
    "model_cooldown",
    "RESOURCE_EXHAUSTED",
    "Too Many Requests",
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
    '"name": "UnknownError"',
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
    text = f"{stdout or ''}\n{stderr or ''}".lower()
    if any(marker.lower() in text for marker in TRANSIENT_MARKERS):
        return "transient_model_error"
    return None
