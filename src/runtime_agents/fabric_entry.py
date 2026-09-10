"""The small agentctl-to-Contract-Fabric process boundary.

The canonical Fabric implementation lives in mac-control.  This module only
resolves and invokes its bounded executable; it deliberately contains no
workflow, task, lease, retry, or snapshot implementation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping


EXPECTED_SCHEMA_SHA256 = "4d5a59c0ad14b91549eaccb5d5222257f6f45a7bb2739298c7b6f37a391e1dcb"
EXPECTED_SPEC_SHA256 = "47eb7d43343ec63e40b1620da439c5b689bda90bc2711bdc7571ce13a059acee"


class FabricEntryError(RuntimeError):
    """The bounded Fabric executable was unavailable or rejected a request."""


def _executable() -> Path:
    configured = os.environ.get("RUNTIME_AGENTS_CONTRACT_FABRIC_BIN")
    candidate = Path(configured).expanduser() if configured else None
    if candidate is None:
        found = shutil.which("contract-fabric")
        if found:
            candidate = Path(found)
    if candidate is None:
        raise FabricEntryError(
            "Contract Fabric executable is not configured; set "
            "RUNTIME_AGENTS_CONTRACT_FABRIC_BIN or install contract-fabric"
        )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise FabricEntryError(f"Contract Fabric executable is unavailable: {candidate}") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise FabricEntryError("Contract Fabric executable is not executable")
    return resolved


def _source_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def invoke(command: str, payload: Mapping[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    """Invoke one bounded Fabric command without ambient Python imports."""

    if not isinstance(command, str) or command not in {
        "materialize-local",
        "admit-coordinated",
        "materialize-coordinated",
        "inspect-local",
        "inspect-coordinated",
    }:
        raise FabricEntryError("unknown Contract Fabric command")
    if not isinstance(payload, Mapping):
        raise FabricEntryError("Contract Fabric request must be an object")
    executable = _executable()
    request = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    env = os.environ.copy()
    # A source boundary is only meaningful when ambient PYTHONPATH cannot
    # redirect the canonical executable's imports.
    env.pop("PYTHONPATH", None)
    try:
        completed = subprocess.run(
            [str(executable), command, "--input", "-"],
            input=request,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FabricEntryError(f"Contract Fabric invocation failed: {type(exc).__name__}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "command rejected request"
        raise FabricEntryError(detail[:400])
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise FabricEntryError("Contract Fabric returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise FabricEntryError("Contract Fabric returned a non-object")
    provenance = value.get("provenance")
    if provenance is not None:
        if not isinstance(provenance, Mapping):
            raise FabricEntryError("Contract Fabric provenance is invalid")
        if provenance.get("schema_sha256") != EXPECTED_SCHEMA_SHA256:
            raise FabricEntryError("Worker Contract schema provenance mismatch")
        if provenance.get("spec_sha256") != EXPECTED_SPEC_SHA256:
            raise FabricEntryError("Worker Contract specification provenance mismatch")
    value["fabric_entrypoint"] = str(executable)
    value["fabric_entrypoint_digest"] = _source_digest(executable)
    return value


def read_json_file(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FabricEntryError("request file is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FabricEntryError("request file must contain a JSON object")
    return value
