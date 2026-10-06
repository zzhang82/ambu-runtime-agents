"""Deterministic loop engine for evidence evaluation, anti-loop blocker detection, and gap classification.

Extracted and adapted from agent-loop-runtime principles:
- Blocker fingerprinting prevents infinite loops on identical failures.
- Gap classification provides structured diagnosis (execution, environment, check_rubric, transient).
- Strict Klaus invariants:
  1. Never parse stdout for gap classification (prevents application-level test string false positives).
  2. Do not strip source code line numbers from tracebacks during normalization.
  3. Hash normalized whole-output blobs to naturally capture error count and context shifts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from runtime_agents import policy as policy_mod


def normalize_check_output(text: str) -> str:
    """Normalize ephemeral system variations while preserving code and error semantics.

    Preserves:
    - Test names, file paths, and source code line numbers.
    - Error messages and failure counts.

    Strips:
    - ANSI escape sequences.
    - ISO timestamps and time logs.
    - Wall-clock durations (e.g. '0.42s', 'in 1.23s', '(0.003 seconds)').
    - Pytest execution summary timing banners.
    - Memory addresses (e.g. '0x7f4a3b2c1d00').
    - Process IDs (e.g. 'pid=12345').
    - Temporary directory paths (/tmp/...).
    """
    if not text:
        return ""

    out = text

    # Strip ANSI escape sequences
    out = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out)

    # Strip ISO-8601 timestamps (e.g. 2026-10-05T14:23:01.123Z)
    out = re.sub(
        r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b",
        "<TIMESTAMP>",
        out,
    )

    # Normalize pytest summary line timing: "=== 1 failed in 0.42s ===" -> "=== 1 failed ==="
    out = re.sub(
        r"(={2,}\s+.*?)\s+in\s+[\d.]+\s*s(\s+={2,})",
        r"\1\2",
        out,
    )

    # Strip wall-clock durations: "(0.003 seconds)" -> "(<DURATION>)"
    out = re.sub(r"\(\d+(?:\.\d+)?\s+seconds?\)", "(<DURATION>)", out)

    # Strip timing suffixes: "in 1.23s" -> "in <DURATION>"
    out = re.sub(r"\bin\s+\d+(?:\.\d+)?s\b", "in <DURATION>", out)

    # Strip raw elapsed durations like " 0.42s " or " [0.42s]"
    out = re.sub(r"(?<=\s)[\d.]+(?:ms|s)\b", "<DURATION>", out)

    # Strip memory addresses: 0x7f4a3b2c1d00
    out = re.sub(r"\b0x[0-9a-fA-F]{6,16}\b", "<MEM_ADDR>", out)

    # Strip PIDs: pid=12345 or pid 12345
    out = re.sub(r"\bpid[= ]\d+\b", "pid=<PID>", out, flags=re.IGNORECASE)

    # Normalize /tmp/... paths: /tmp/pytest-of-runner/pytest-0/... -> /tmp/<TEMPDIR>
    out = re.sub(r"/tmp/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*", "/tmp/<TEMPDIR>", out)

    # Strip trailing whitespace on each line
    lines = [line.rstrip() for line in out.splitlines()]
    # Collapse multiple consecutive blank lines
    collapsed: list[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                collapsed.append("")
                prev_blank = True
        else:
            collapsed.append(line)
            prev_blank = False

    return "\n".join(collapsed).strip()


def fingerprint_check_failure(stdout: str, stderr: str, returncode: int) -> str:
    """Compute a deterministic content hash of the normalized check failure.

    Hashes returncode, normalized stderr, and normalized stdout together as one blob.
    Any shift in failure count, failing test name, or error line number produces a distinct hash.
    """
    norm_stdout = normalize_check_output(stdout or "")
    norm_stderr = normalize_check_output(stderr or "")
    blob = f"returncode:{returncode}\n---stderr---\n{norm_stderr}\n---stdout---\n{norm_stdout}\n"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def classify_gap(stdout: str, stderr: str, returncode: int) -> tuple[str, str]:
    """Classify the failure into an actionable gap kind and human-readable detail.

    Adheres strictly to Klaus Invariant:
    Never parse stdout for gap classification to prevent application test assertions
    (e.g. `assert user == 'not found'`) from triggering false environment errors.
    Only inspect returncode and stderr.
    """
    if returncode == 0:
        return "none", "Check passed"

    # Shell returncodes for invalid command or permission issues
    if returncode == 127:
        return "check_rubric", "Check command binary not found (shell exit 127)"
    if returncode == 126:
        return "check_rubric", "Check command not executable or permission denied (shell exit 126)"

    stderr_text = stderr or ""

    # Check for transient errors in stderr (e.g. 429, timeout, connection reset)
    if policy_mod.classify_failure("", stderr_text, returncode) == "transient_model_error":
        return "transient", "Transient API, network, or server error detected in stderr"

    # Check for shell-level environment errors in stderr ONLY
    # Example: "bash: cargo: command not found" or "sh: 1: mypy: not found"
    shell_env_patterns = [
        r"\b(?:bash|sh|zsh):\s*[^:\n]+:\s*command not found\b",
        r"\b(?:bash|sh|zsh):\s*line\s+\d+:\s*[^:\n]+:\s*(?:command\s+)?not found\b",
        r"\bcommand not found:\s*\w+\b",
    ]
    for pattern in shell_env_patterns:
        if re.search(pattern, stderr_text, re.IGNORECASE):
            return "environment", "Missing system binary or tool dependency reported by shell"

    # Default: execution gap (the code under test failed an assertion or raised an error)
    return "execution", "Code execution or test assertion failure"


def should_halt(
    fingerprint: str,
    failure_counts: dict[str, int],
    max_same_failure: int = 2,
) -> tuple[bool, dict[str, int], int]:
    """Determine whether the loop should halt due to an identical repeated blocker.

    Returns:
    (should_stop, updated_failure_counts, current_count_for_this_fingerprint)
    """
    counts = dict(failure_counts)
    count = counts.get(fingerprint, 0) + 1
    counts[fingerprint] = count
    return count >= max_same_failure, counts, count


@dataclass
class RoundEvaluation:
    round_num: int
    returncode: int
    fingerprint: str
    gap_kind: str
    gap_detail: str
    repeated_count: int
    halted: bool = False
