"""Bounded, read-only quota observation workflow.

The watcher is intentionally a small vertical loop.  It reads an existing
schedule projection, uses :func:`runtime_agents.schedules.schedule_due`, and
records private local evidence.  It does not enqueue agent work, call an LLM,
write AMB, or change routing/provider state.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit

from runtime_agents import model_catalog, schedules, state


WORKFLOW_ID = "quota-watcher"
SCHEDULES_NAME = "schedules.jsonl"
STATE_DIR_NAME = "quota-watcher"
RECEIPTS_NAME = "receipts"
EVIDENCE_NAME = "evidence"
OBSERVATIONS_NAME = "observations.jsonl"
EVENTS_NAME = "change-events.jsonl"
LOCK_NAME = "watcher.lock"
DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0
DEFAULT_STALE_ATTEMPT_SECONDS = 120.0


class WatcherError(RuntimeError):
    """A malformed or unsafe watcher input; callers should fail closed."""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now_iso() -> str:
    return _utc_now().isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _state_root(state_home: str | os.PathLike[str]) -> Path:
    root = Path(state_home).expanduser()
    if not str(root):
        raise WatcherError("state home is empty")
    return root / STATE_DIR_NAME


def _ensure_root(root: Path) -> None:
    state_home = root.parent
    state_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if state_home.stat().st_mode & 0o077:
            raise WatcherError(f"state home must not be group/world accessible: {state_home}")
    except OSError as exc:
        raise WatcherError(f"cannot inspect watcher state home: {state_home}: {type(exc).__name__}") from exc
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError as exc:
        raise WatcherError(f"cannot protect watcher state: {root}: {type(exc).__name__}") from exc
    for name in (RECEIPTS_NAME, EVIDENCE_NAME):
        (root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            (root / name).chmod(0o700)
        except OSError as exc:
            raise WatcherError(f"cannot protect watcher directory: {root / name}") from exc


@contextlib.contextmanager
def _locked(root: Path) -> Iterator[None]:
    """Serialize receipt, observation, and event updates in one state root."""

    _ensure_root(root)
    lock_path = root / LOCK_NAME
    try:
        with lock_path.open("a+", encoding="utf-8") as handle:
            lock_path.chmod(0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise WatcherError(f"watcher state lock unavailable: {type(exc).__name__}") from exc


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except OSError as exc:
        raise WatcherError(f"cannot write watcher evidence: {path}: {type(exc).__name__}") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o600)
    except OSError as exc:
        raise WatcherError(f"cannot append watcher evidence: {path}: {type(exc).__name__}") from exc


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        rows = state.read_jsonl(path)
    except (OSError, ValueError) as exc:
        raise WatcherError(f"malformed watcher state: {path}: {type(exc).__name__}") from exc
    return [row for row in rows if isinstance(row, dict)]


def _receipt_path(root: Path, occurrence_id: str) -> Path:
    return root / RECEIPTS_NAME / f"{_fingerprint(occurrence_id)}.json"


def _schedule_state_path(root: Path) -> Path:
    return root / "schedule-state.json"


def _load_schedule_state(root: Path) -> dict[str, Any]:
    payload = _read_json(_schedule_state_path(root))
    return payload if payload is not None else {}


def _save_schedule_state(root: Path, payload: dict[str, Any]) -> None:
    _write_private_json(_schedule_state_path(root), payload)


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _safe_source_identity(url: str | None) -> str | None:
    """Keep scheme/host/path only; never persist query strings or credentials."""

    if not url:
        return None
    try:
        parsed = urlsplit(str(url))
        if not parsed.scheme or not parsed.hostname:
            return None
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        path = parsed.path or "/"
        return f"{parsed.scheme}://{host}{path}".rstrip("/") or f"{parsed.scheme}://{host}/"
    except ValueError:
        return None


def _source_summary(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {"ok": False, "freshness": "unavailable", "error": "malformed_source"}
    ok = bool(source.get("ok"))
    cached = bool(source.get("used_cached_catalog"))
    summary: dict[str, Any] = {
        "ok": ok,
        "freshness": "fresh" if ok else ("cached" if cached else "unavailable"),
    }
    if source.get("fetched_at"):
        summary["observed_at"] = source["fetched_at"]
    if source.get("error"):
        summary["error"] = str(source["error"])
    if cached:
        summary["used_cached_catalog"] = True
    if source.get("provider"):
        summary["provider"] = str(source["provider"])
    return summary


def _error_is_retryable(error: Any) -> bool:
    if not error:
        return False
    name = str(error)
    return name in {
        "TimeoutError",
        "URLError",
        "ConnectionError",
        "ConnectionResetError",
        "OSError",
        "socket.timeout",
    } or "timeout" in name.lower() or "connection" in name.lower()


def _normalised_models(snapshot: dict[str, Any] | None) -> list[dict[str, str]]:
    result = []
    for item in (snapshot or {}).get("models") or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        row = {"id": item["id"]}
        if isinstance(item.get("owned_by"), str):
            row["owned_by"] = item["owned_by"]
        result.append(row)
    return sorted(result, key=lambda row: (row["id"], row.get("owned_by", "")))


def _quota_policy(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Reuse the collector policy but fail closed when a successful payload has no metrics."""

    policy = model_catalog.openai_quota_policy(snapshot)
    source = ((snapshot or {}).get("sources") or {}).get("quota") or {}
    data = source.get("data") if isinstance(source, dict) else None
    if not source.get("ok") or source.get("provider") != "openai" or not isinstance(data, dict):
        return policy
    values: list[float] = []
    for key in ("weekly_left", "weekly_avg_left", "weekly_min_left"):
        value = data.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
        elif isinstance(value, str):
            try:
                values.append(float(value.strip().removesuffix("%")))
            except ValueError:
                pass
    for row in data.get("rows") or []:
        if isinstance(row, dict):
            value = row.get("weekly_left")
            if isinstance(value, (int, float)):
                values.append(float(value))
            elif isinstance(value, str):
                try:
                    values.append(float(value.strip().removesuffix("%")))
                except ValueError:
                    pass
    if not values and not data.get("limited") and not data.get("exhausted"):
        return {"state": "unknown", "reason": "openai_quota_metrics_missing", "weekly_average_left": None, "weekly_minimum_left": None}
    return policy


def collect_observation(
    *,
    state_home: str | os.PathLike[str],
    schedule_id: str,
    occurrence_id: str,
    logical_run_id: str,
    attempt_id: str,
    fetch_json: Callable[[str, str | None], Any] | None = None,
) -> dict[str, Any]:
    """Collect one sanitized observation using the existing model collector."""

    root = _state_root(state_home)
    _ensure_root(root)
    previous = model_catalog.load_snapshot(state_home)
    source_identity: dict[str, str | None] = {}
    try:
        cpa = model_catalog.resolve_cpa_config()
        source_identity["cpa"] = _safe_source_identity(cpa.get("base_url"))
    except Exception:
        source_identity["cpa"] = None
    source_identity["quota"] = _safe_source_identity(
        os.environ.get("RUNTIME_AGENTS_QUOTA_WIDGET_URL", model_catalog.DEFAULT_QUOTA_URL)
    )

    observed_at = now_iso()
    try:
        if fetch_json is None:
            snapshot = model_catalog.refresh_snapshot(state_home)
        else:
            snapshot = model_catalog.refresh_snapshot(state_home, fetch_json=fetch_json)
    except Exception as exc:  # a collector crash is never a contract mismatch
        normalized = {"quota_state": "unknown", "quota_reason": "collector_execution_failed", "models": []}
        return {
            "observed_at": observed_at,
            "collection_status": "unavailable",
            "observation_freshness": "unavailable",
            "source_identity": source_identity,
            "source_status": {},
            "normalized": normalized,
            "state_fingerprint": _fingerprint(normalized),
            "quota_state": "unknown",
            "quota_reason": "collector_execution_failed",
            "error_classes": [type(exc).__name__],
            "retryable": _error_is_retryable(type(exc).__name__),
            "terminal_error": not _error_is_retryable(type(exc).__name__),
            "schedule_id": schedule_id,
            "occurrence_id": occurrence_id,
            "logical_run_id": logical_run_id,
            "attempt_id": attempt_id,
        }

    sources = (snapshot or {}).get("sources") or {}
    source_status = {name: _source_summary(sources.get(name)) for name in ("cpa", "quota")}
    successful = [summary.get("ok") for summary in source_status.values()]
    errors = sorted({str(summary["error"]) for summary in source_status.values() if summary.get("error")})
    has_success = any(successful)
    all_success = bool(successful) and all(successful)
    cached_catalog = bool((source_status.get("cpa") or {}).get("freshness") == "cached")
    if all_success:
        collection_status = "fresh"
    elif has_success:
        collection_status = "partial"
    elif previous is not None:
        collection_status = "stale"
    else:
        collection_status = "unavailable"

    if collection_status == "stale" and previous is not None:
        quota_policy = _quota_policy(previous)
        quota_source = "cached"
        models = _normalised_models(previous)
    else:
        quota_policy = _quota_policy(snapshot)
        quota_source = "fresh" if (source_status.get("quota") or {}).get("ok") else "unavailable"
        models = _normalised_models(snapshot)

    normalized = {
        "quota_state": quota_policy.get("state", "unknown"),
        "quota_reason": quota_policy.get("reason", "unknown"),
        "weekly_average_left": quota_policy.get("weekly_average_left"),
        "weekly_minimum_left": quota_policy.get("weekly_minimum_left"),
        "quota_source": quota_source,
        "models": models,
    }
    error_classes = errors or []
    retryable = collection_status in {"partial", "unavailable"} and any(_error_is_retryable(error) for error in error_classes)
    terminal_error = collection_status == "unavailable" and not retryable
    return {
        "observed_at": str((snapshot or {}).get("generated_at") or observed_at),
        "collection_status": collection_status,
        "observation_freshness": collection_status,
        "source_identity": source_identity,
        "source_status": source_status,
        "normalized": normalized,
        "state_fingerprint": _fingerprint(normalized),
        "quota_state": normalized["quota_state"],
        "quota_reason": normalized["quota_reason"],
        "error_classes": error_classes,
        "retryable": retryable,
        "terminal_error": terminal_error,
        "cached_catalog": cached_catalog,
        "schedule_id": schedule_id,
        "occurrence_id": occurrence_id,
        "logical_run_id": logical_run_id,
        "attempt_id": attempt_id,
    }


def _claim_occurrence(
    *,
    root: Path,
    schedule_id: str,
    occurrence_id: str,
    logical_run_id: str,
    started_at: str,
    stale_attempt_seconds: float,
) -> tuple[dict[str, Any], str, bool]:
    receipt_path = _receipt_path(root, occurrence_id)
    with _locked(root):
        existing = _read_json(receipt_path)
        if existing:
            status = existing.get("status")
            if status in {"completed", "failed"}:
                return existing, "", False
            if status == "running":
                started = _parse_timestamp((existing.get("attempts") or [{}])[-1].get("started_at"))
                current = _parse_timestamp(started_at) or _utc_now()
                age = (current - started).total_seconds() if started else 0.0
                if age <= max(0.0, stale_attempt_seconds):
                    return existing, "", False
                attempts = existing.setdefault("attempts", [])
                if attempts:
                    attempts[-1].update({
                        "finished_at": started_at,
                        "outcome": "interrupted",
                        "failure_class": "process_interrupted",
                    })
                existing.update({"status": "interrupted", "updated_at": started_at})
                _write_private_json(receipt_path, existing)
        attempt_id = f"attempt-{uuid.uuid4().hex}"
        receipt = existing or {
            "schema_version": 1,
            "workflow_id": WORKFLOW_ID,
            "schedule_id": schedule_id,
            "occurrence_id": occurrence_id,
            "logical_run_id": logical_run_id,
            "attempts": [],
        }
        receipt.update({"status": "running", "updated_at": started_at, "last_attempt_id": attempt_id})
        receipt.setdefault("attempts", []).append({"attempt_id": attempt_id, "started_at": started_at, "outcome": "running"})
        _write_private_json(receipt_path, receipt)
        return receipt, attempt_id, True


def _record_observation(root: Path, observation: dict[str, Any]) -> dict[str, Any] | None:
    evidence_path = root / EVIDENCE_NAME / f"{observation['observation_id']}.json"
    observation = {**observation, "recorded_at": now_iso(), "evidence_ref": str(evidence_path)}
    _write_private_json(evidence_path, observation)
    events_path = root / EVENTS_NAME
    observations_path = root / OBSERVATIONS_NAME
    with _locked(root):
        _append_jsonl(observations_path, observation)
        prior = None
        for row in reversed(_read_jsonl(observations_path)[:-1]):
            if row.get("workflow_id") == WORKFLOW_ID and row.get("schedule_id") == observation.get("schedule_id"):
                prior = row
                break
        event = None
        if prior is None or prior.get("state_fingerprint") != observation.get("state_fingerprint"):
            event = {
                "schema_version": 1,
                "event_id": f"event-{uuid.uuid4().hex}",
                "event_type": "quota_state_changed",
                "workflow_id": WORKFLOW_ID,
                "schedule_id": observation.get("schedule_id"),
                "occurrence_id": observation.get("occurrence_id"),
                "logical_run_id": observation.get("logical_run_id"),
                "observation_id": observation.get("observation_id"),
                "recorded_at": now_iso(),
                "previous_state_fingerprint": prior.get("state_fingerprint") if prior else None,
                "state_fingerprint": observation.get("state_fingerprint"),
                "quota_state": observation.get("quota_state"),
                "collection_status": observation.get("collection_status"),
                "evidence_ref": observation.get("evidence_ref"),
            }
            _append_jsonl(events_path, event)
    return event


def _finish_attempt(
    *,
    root: Path,
    occurrence_id: str,
    attempt_id: str,
    status: str,
    outcome: str,
    failure_class: str | None = None,
    observation: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    retry_disposition: str = "not_needed",
    next_due_at: str | None = None,
) -> dict[str, Any]:
    path = _receipt_path(root, occurrence_id)
    finished_at = now_iso()
    with _locked(root):
        receipt = _read_json(path) or {}
        for attempt in reversed(receipt.get("attempts") or []):
            if attempt.get("attempt_id") == attempt_id:
                attempt.update({"finished_at": finished_at, "outcome": outcome})
                if failure_class:
                    attempt["failure_class"] = failure_class
                if observation:
                    attempt["observation_id"] = observation.get("observation_id")
                    attempt["evidence_ref"] = observation.get("evidence_ref")
                break
        receipt.update({
            "status": status,
            "updated_at": finished_at,
            "last_attempt_id": attempt_id,
            "outcome": outcome,
            "retry_disposition": retry_disposition,
            "next_due_at": next_due_at,
        })
        if failure_class:
            receipt["failure_class"] = failure_class
        if observation:
            receipt.update({
                "observed_at": observation.get("observed_at"),
                "observation_id": observation.get("observation_id"),
                "evidence_ref": observation.get("evidence_ref"),
                "collection_status": observation.get("collection_status"),
                "observation_freshness": observation.get("observation_freshness"),
                "quota_state": observation.get("quota_state"),
                "state_fingerprint": observation.get("state_fingerprint"),
                "change_event_id": event.get("event_id") if event else None,
            })
        _write_private_json(path, receipt)
        return receipt


def _next_due_at(schedule: dict[str, Any], when: dt.datetime, horizon_minutes: int = 7 * 24 * 60) -> str | None:
    expression = schedule.get("cron")
    if not expression:
        return None
    candidate = when.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    for _ in range(max(1, horizon_minutes)):
        try:
            if schedules.cron_matches_now(expression, candidate):
                return candidate.isoformat()
        except Exception:
            return None
        candidate += dt.timedelta(minutes=1)
    return None


def execute_occurrence(
    schedule: dict[str, Any],
    *,
    state_home: str | os.PathLike[str],
    when: dt.datetime | None = None,
    fetch_json: Callable[[str, str | None], Any] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    stale_attempt_seconds: float = DEFAULT_STALE_ATTEMPT_SECONDS,
) -> dict[str, Any]:
    """Execute one logical occurrence; retries keep the logical run stable."""

    when = when or dt.datetime.now().astimezone()
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    schedule_id = str(schedule.get("schedule_id") or schedule.get("name") or "quota-watcher")
    due_window = schedules.due_window_id(when)
    occurrence_id = f"{schedule_id}:{due_window}"
    logical_run_id = f"{WORKFLOW_ID}:{occurrence_id}"
    root = _state_root(state_home)
    _ensure_root(root)
    receipt, attempt_id, claimed = _claim_occurrence(
        root=root,
        schedule_id=schedule_id,
        occurrence_id=occurrence_id,
        logical_run_id=logical_run_id,
        started_at=now_iso(),
        stale_attempt_seconds=stale_attempt_seconds,
    )
    if not claimed:
        status = receipt.get("status")
        return {"status": "duplicate" if status in {"completed", "failed"} else "in_progress", "attempted": False, "receipt": receipt}

    max_attempts = max(1, int(max_attempts))
    last_observation = None
    last_event = None
    retry_disposition = "not_needed"
    for attempt_number in range(max_attempts):
        if attempt_number:
            delay = max(0.0, float(retry_backoff_seconds)) * (2 ** (attempt_number - 1))
            if delay:
                sleep(delay)
            with _locked(root):
                receipt = _read_json(_receipt_path(root, occurrence_id)) or receipt
                attempt_id = f"attempt-{uuid.uuid4().hex}"
                receipt["status"] = "running"
                receipt["updated_at"] = now_iso()
                receipt["last_attempt_id"] = attempt_id
                receipt.setdefault("attempts", []).append({"attempt_id": attempt_id, "started_at": now_iso(), "outcome": "running"})
                _write_private_json(_receipt_path(root, occurrence_id), receipt)

        collected = collect_observation(
            state_home=state_home,
            schedule_id=schedule_id,
            occurrence_id=occurrence_id,
            logical_run_id=logical_run_id,
            attempt_id=attempt_id,
            fetch_json=fetch_json,
        )
        observation = {
            "schema_version": 1,
            "workflow_id": WORKFLOW_ID,
            "observation_id": f"observation-{uuid.uuid4().hex}",
            "schedule_id": schedule_id,
            "occurrence_id": occurrence_id,
            "logical_run_id": logical_run_id,
            "attempt_id": attempt_id,
            **{key: value for key, value in collected.items() if key not in {"retryable", "terminal_error", "cached_catalog"}},
        }
        last_observation = observation
        last_event = _record_observation(root, observation)
        observation["evidence_ref"] = str(root / EVIDENCE_NAME / f"{observation['observation_id']}.json")
        usable = observation.get("collection_status") in {"fresh", "partial", "stale"}
        retryable = bool(collected.get("retryable")) and not usable
        if usable:
            retry_disposition = "retry_not_needed" if attempt_number == 0 else "retry_succeeded"
            receipt = _finish_attempt(
                root=root,
                occurrence_id=occurrence_id,
                attempt_id=attempt_id,
                status="completed",
                outcome="completed",
                observation=observation,
                event=last_event,
                retry_disposition=retry_disposition,
                next_due_at=_next_due_at(schedule, when),
            )
            break
        if retryable and attempt_number + 1 < max_attempts:
            retry_disposition = "retry_scheduled"
            _finish_attempt(
                root=root,
                occurrence_id=occurrence_id,
                attempt_id=attempt_id,
                status="running",
                outcome="retryable_failure",
                failure_class="source_unavailable",
                observation=observation,
                event=last_event,
                retry_disposition=retry_disposition,
                next_due_at=_next_due_at(schedule, when),
            )
            continue
        retry_disposition = "retry_exhausted" if retryable else "terminal_failure"
        failure_class = "source_unavailable" if retryable else (collected.get("error_classes") or ["collection_failed"])[0]
        receipt = _finish_attempt(
            root=root,
            occurrence_id=occurrence_id,
            attempt_id=attempt_id,
            status="failed",
            outcome="failed",
            failure_class=str(failure_class),
            observation=observation,
            event=last_event,
            retry_disposition=retry_disposition,
            next_due_at=_next_due_at(schedule, when),
        )
    else:  # pragma: no cover - max_attempts is normalized above
        receipt = _read_json(_receipt_path(root, occurrence_id)) or receipt
    return {"status": "executed", "attempted": True, "receipt": receipt, "observation": last_observation, "event": last_event}


def _load_latest_schedules(state_home: str | os.PathLike[str]) -> list[dict[str, Any]]:
    path = Path(state_home).expanduser() / SCHEDULES_NAME
    events = _read_jsonl(path)
    by_id = state.latest_by_id(events, "schedule_id")
    by_name = state.latest_by_id(events, "name")
    merged = {**by_name, **by_id}
    return [row for row in merged.values() if isinstance(row, dict) and not row.get("removed")]


def _select_schedules(state_home: str | os.PathLike[str], schedule_id: str | None) -> list[dict[str, Any]]:
    schedules_found = _load_latest_schedules(state_home)
    if schedule_id:
        selected = [row for row in schedules_found if str(row.get("schedule_id")) == schedule_id or str(row.get("name")) == schedule_id]
    else:
        selected = [row for row in schedules_found if row.get("workflow") == WORKFLOW_ID]
    return selected


def run_due(
    schedule: dict[str, Any],
    *,
    state_home: str | os.PathLike[str],
    when: dt.datetime | None = None,
    fetch_json: Callable[[str, str | None], Any] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    stale_attempt_seconds: float = DEFAULT_STALE_ATTEMPT_SECONDS,
) -> dict[str, Any]:
    """Use the existing cron due check and localize only watcher schedule state."""

    when = when or dt.datetime.now().astimezone()
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    root = _state_root(state_home)
    _ensure_root(root)
    schedule_id = str(schedule.get("schedule_id") or schedule.get("name") or "quota-watcher")
    local_state = _load_schedule_state(root)
    effective = dict(schedule)
    local_last = ((local_state.get(schedule_id) or {}).get("last_due_window"))
    if local_last:
        effective["last_due_window"] = local_last
    due, reason = schedules.schedule_due(effective, when)
    if not due:
        return {"status": "not_due", "attempted": False, "schedule_id": schedule_id, "reason": reason, "now": when.isoformat()}
    result = execute_occurrence(
        schedule,
        state_home=state_home,
        when=when,
        fetch_json=fetch_json,
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        sleep=sleep,
        stale_attempt_seconds=stale_attempt_seconds,
    )
    receipt = result.get("receipt") or {}
    local_state[schedule_id] = {
        "last_due_window": schedules.due_window_id(when),
        "last_due_at": when.isoformat(),
        "last_status": receipt.get("status"),
        "last_occurrence_id": receipt.get("occurrence_id"),
        "next_due_at": receipt.get("next_due_at"),
        "updated_at": now_iso(),
    }
    _save_schedule_state(root, local_state)
    return {**result, "schedule_id": schedule_id, "due_window": schedules.due_window_id(when), "now": when.isoformat()}


def run_due_loop(
    *,
    state_home: str | os.PathLike[str],
    schedule: dict[str, Any] | None = None,
    schedule_id: str | None = None,
    occurrences: int = 1,
    timeout_seconds: float = 60.0,
    poll_interval: float = 5.0,
    fetch_json: Callable[[str, str | None], Any] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], dt.datetime] | None = None,
    stale_attempt_seconds: float = DEFAULT_STALE_ATTEMPT_SECONDS,
) -> dict[str, Any]:
    """Run a bounded foreground pilot; never leaves a background scheduler."""

    if occurrences < 1:
        raise WatcherError("occurrences must be positive")
    if schedule is not None:
        selected = [schedule]
    else:
        selected = _select_schedules(state_home, schedule_id)
    if not selected:
        raise WatcherError("no quota-watcher schedule selected")
    if len(selected) > 1 and not schedule_id:
        raise WatcherError("more than one quota-watcher schedule; pass --schedule-id")
    selected_schedule = selected[0]
    clock = clock or (lambda: dt.datetime.now().astimezone())
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    while len([row for row in results if row.get("attempted")]) < occurrences:
        if time.monotonic() - started >= max(0.0, timeout_seconds):
            break
        current = clock()
        result = run_due(
            selected_schedule,
            state_home=state_home,
            when=current,
            fetch_json=fetch_json,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            sleep=sleep,
            stale_attempt_seconds=stale_attempt_seconds,
        )
        if result.get("status") != "not_due" or not results or results[-1].get("reason") != result.get("reason"):
            results.append(result)
        if len([row for row in results if row.get("attempted")]) >= occurrences:
            break
        sleep(max(0.0, poll_interval))
    attempted = [row for row in results if row.get("attempted")]
    return {
        "workflow_id": WORKFLOW_ID,
        "schedule_id": selected_schedule.get("schedule_id") or selected_schedule.get("name"),
        "target_occurrences": occurrences,
        "attempted_occurrences": len(attempted),
        "complete": len(attempted) >= occurrences,
        "results": results,
    }


def _json_print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quota-watcher")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state-home", required=True, help="isolated state directory; never defaults to production state")
    common.add_argument("--schedule-id")
    common.add_argument("--occurrences", type=int, default=1)
    common.add_argument("--timeout", type=float, default=60.0)
    common.add_argument("--poll-interval", type=float, default=5.0)
    common.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    common.add_argument("--retry-backoff", type=float, default=DEFAULT_RETRY_BACKOFF_SECONDS)
    common.add_argument("--stale-attempt-seconds", type=float, default=DEFAULT_STALE_ATTEMPT_SECONDS)
    common.add_argument("--json", action="store_true")

    run_due_parser = sub.add_parser("run-due", parents=[common], help="run due quota-watcher schedule from schedules.jsonl")
    run_due_parser.set_defaults(ephemeral=False)
    pilot_parser = sub.add_parser("pilot", parents=[common], help="bounded foreground pilot using existing cron due logic")
    pilot_parser.add_argument("--cron", default="* * * * *")
    pilot_parser.set_defaults(ephemeral=True)
    args = parser.parse_args(argv)
    try:
        candidate = Path(args.state_home).expanduser().resolve()
        production = Path(os.environ.get("RUNTIME_AGENTS_STATE_HOME", str(Path.home() / ".local/share/runtime-agents"))).expanduser().resolve()
        if candidate == production or production in candidate.parents:
            raise WatcherError("state home must be isolated from runtime-agents production state")
        if args.ephemeral:
            schedule = {
                "workflow": WORKFLOW_ID,
                "schedule_id": args.schedule_id or "quota-watcher-pilot",
                "name": args.schedule_id or "quota-watcher-pilot",
                "enabled": True,
                "cron": args.cron,
                "type": "read_only",
            }
            payload = run_due_loop(
                state_home=args.state_home,
                schedule=schedule,
                occurrences=args.occurrences,
                timeout_seconds=args.timeout,
                poll_interval=args.poll_interval,
                max_attempts=args.max_attempts,
                retry_backoff_seconds=args.retry_backoff,
                stale_attempt_seconds=args.stale_attempt_seconds,
            )
        else:
            payload = run_due_loop(
                state_home=args.state_home,
                schedule_id=args.schedule_id,
                occurrences=args.occurrences,
                timeout_seconds=args.timeout,
                poll_interval=args.poll_interval,
                max_attempts=args.max_attempts,
                retry_backoff_seconds=args.retry_backoff,
                stale_attempt_seconds=args.stale_attempt_seconds,
            )
    except WatcherError as exc:
        error = {"workflow_id": WORKFLOW_ID, "status": "blocked", "error": str(exc)}
        if args.json:
            _json_print(error)
        else:
            print(f"QUOTA_WATCHER BLOCKED: {exc}", file=sys.stderr)
        return 2
    _json_print(payload)
    return 0 if payload.get("complete") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
