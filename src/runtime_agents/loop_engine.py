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
from pathlib import Path
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

    # Check for evaluation artifact failure explicitly in stderr
    if "evaluation artifact check failed:" in stderr_text.lower():
        for line in stderr_text.splitlines():
            if "evaluation artifact check failed:" in line.lower():
                return "execution", line.strip()

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


def check_eval_artifacts(run_cwd: Path, artifacts: list[str]) -> tuple[bool, str]:
    """Verify that all declared evaluation artifacts exist and are non-empty regular files.

    Returns:
    (all_passed, error_message)
    """
    if not artifacts:
        return True, ""

    root = run_cwd.resolve()
    for rel_path in artifacts:
        if not rel_path or not rel_path.strip():
            continue
        clean = rel_path.strip()
        p = (root / clean).resolve()
        if not p.is_relative_to(root):
            return False, f"Evaluation artifact path escapes workspace: {clean}"
        if not p.exists():
            return False, f"Required evaluation artifact does not exist: {clean}"
        if not p.is_file():
            return False, f"Required evaluation artifact is not a regular file: {clean}"
        if p.stat().st_size == 0:
            return False, f"Required evaluation artifact is empty (0 bytes): {clean}"

    return True, ""


def build_iteration_prompt(
    effective_goal: str,
    check_command: str | None,
    eval_artifacts: list[str] | None,
    last_stdout: str,
    last_stderr: str,
    gap_kind: str,
    gap_detail: str,
    autonomy: str = "workspace_write",
) -> str:
    """Construct a gap-aware prompt tailored to the diagnosed failure category."""
    if autonomy == "read_only":
        action_instruction = "Analyze the failure and report the likely cause and next safe action. Do not edit files or attempt to fix the workspace."
    elif gap_kind == "environment":
        action_instruction = f"The check failed due to a missing dependency or system binary in the environment: {gap_detail}. Analyze whether this is fixable within workspace authority or if an alternative local approach/tool is needed."
    elif gap_kind == "check_rubric":
        action_instruction = f"The check command itself failed to execute properly: {gap_detail}. Inspect the command path, syntax, or binary."
    elif gap_kind == "transient":
        action_instruction = f"The check encountered a transient error: {gap_detail}. Verify connectivity or retry safely without corrupting the workspace."
    else:
        action_instruction = "Fix the workspace locally so the check passes. Do not push, deploy, edit global config, touch secrets, install global packages, or delete outside the workspace."

    sections = [
        f"Goal:\n{effective_goal.strip()}",
    ]
    if check_command:
        sections.append(f"Check command:\n{check_command.strip()}")
    if eval_artifacts:
        arts_str = "\n".join(f"- {a}" for a in eval_artifacts)
        sections.append(f"Required evaluation artifacts:\n{arts_str}")

    sections.append(f"Failure diagnosis:\n[{gap_kind}] {gap_detail}\n\n{action_instruction}")

    if last_stdout and last_stdout.strip():
        sections.append(f"Previous check stdout:\n{last_stdout.strip()}")
    if last_stderr and last_stderr.strip():
        sections.append(f"Previous check stderr:\n{last_stderr.strip()}")

    sections.append(
        "Shared tool guidance: if your runtime exposes Agent Memory Bridge, Context7, or Playwright tools, use them as evidence lanes when relevant. Prefer Agent Memory Bridge for project/domain memory, Context7 for current library docs, and Playwright for browser/UI validation. Do not assume those tools exist; proceed with local files and commands when unavailable."
    )

    return "\n\n".join(sections)
