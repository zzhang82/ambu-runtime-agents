"""CPA model catalog, quota preflight, and role recommendation helpers."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


DEFAULT_QUOTA_URL = os.environ.get("CPA_QUOTA_URL", "http://localhost:8441/widget")
SNAPSHOT_NAME = "model-catalog.json"
COOLDOWNS_NAME = "model-cooldowns.json"
DEFAULT_STALE_SECONDS = 300
DEFAULT_CANDIDATES = {
    "recon": ["local/gemini-3.8-flash-high", "local/gemini-3.7-flash-high", "local/gpt-6-luna"],
    "bounded_work": ["local/gemini-3.7-flash-high", "local/gpt-6-luna", "local/gemini-3.8-flash-high"],
    "implementation_ready": ["local/grok-4.7-build-fast", "local/gpt-6-astra", "local/gemini-3.8-flash-high"],
    "design_planning": ["local/grok-4.7", "local/gpt-6-astra", "local/gpt-6.1-sol"],
    "deep_work": ["local/gpt-6-astra", "local/gpt-6.1-sol", "local/grok-4.7"],
    "review": ["local/gpt-6-astra", "local/gpt-6.1-sol", "local/grok-4.7", "local/gemini-3.8-flash-high"],
    "orchestrator": ["local/gpt-6.1-sol", "local/gpt-6-astra", "local/gemini-3.8-flash-high"],
}
SENSITIVE_KEYS = {"apikey", "api_key", "authorization", "token", "secret", "password"}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def snapshot_path(state_home=None):
    return Path(state_home or os.environ.get("RUNTIME_AGENTS_STATE_HOME", Path.home() / ".local/share/runtime-agents")) / SNAPSHOT_NAME


def cooldowns_path(state_home=None):
    return Path(state_home or os.environ.get("RUNTIME_AGENTS_STATE_HOME", Path.home() / ".local/share/runtime-agents")) / COOLDOWNS_NAME


def _opencode_config_path():
    return Path(os.environ.get("RUNTIME_AGENTS_OPENCODE_CONFIG", Path.home() / ".config/opencode/opencode.json")).expanduser()


def _opencode_config():
    try:
        return json.loads(_opencode_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve_cpa_config():
    """Resolve gateway details without persisting or printing the API key."""
    config = _opencode_config()
    local = ((config.get("provider") or {}).get("local") or {})
    options = local.get("options") or {}
    base_url = (os.environ.get("RUNTIME_AGENTS_CPA_BASE_URL") or os.environ.get("CPA_BASE_URL")
                or options.get("baseURL") or options.get("base_url"))
    api_key = (os.environ.get("RUNTIME_AGENTS_CPA_API_KEY") or os.environ.get("CPA_API_KEY")
               or options.get("apiKey") or options.get("api_key"))
    return {"base_url": str(base_url).rstrip("/") if base_url else None, "api_key": api_key}


def configured_local_models():
    local = ((_opencode_config().get("provider") or {}).get("local") or {})
    models = local.get("models") or {}
    return sorted(f"local/{model_id}" for model_id in models if isinstance(model_id, str))


def deprecated_local_models():
    local = ((_opencode_config().get("provider") or {}).get("local") or {})
    models = local.get("models") or {}
    return {
        f"local/{model_id}"
        for model_id, metadata in models.items()
        if isinstance(model_id, str) and isinstance(metadata, dict) and metadata.get("status") == "deprecated"
    }


def parse_catalog(payload):
    """Normalize OpenAI-compatible /v1/models response to safe, stable records."""
    records = payload.get("data", []) if isinstance(payload, dict) else []
    result = []
    for item in records:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result.append({"id": item["id"], "owned_by": item.get("owned_by") or "unknown"})
    return sorted(result, key=lambda item: item["id"])


def _fetch_json(url, api_key=None, timeout=5):
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:  # nosec B310 - explicitly configured local gateway
        return json.loads(response.read().decode("utf-8"))


def _safe_value(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SENSITIVE_KEYS or normalized.endswith("_token") or "secret" in normalized or "password" in normalized:
                continue
            result[str(key)] = _safe_value(item)
        return result
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def _sanitized_quota(payload):
    safe = _safe_value(payload) if isinstance(payload, dict) else {}
    if not isinstance(safe, dict):
        safe = {}
    result = {
        key: safe[key]
        for key in (
            "weekly_left",
            "weekly_avg_left",
            "weekly_min_left",
            "status",
            "updated",
            "limited",
            "exhausted",
        )
        if key in safe
    }
    rows = []
    raw_rows = safe.get("rows", [])
    if not isinstance(raw_rows, list):
        raw_rows = []
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        rows.append({key: row[key] for key in ("weekly_left", "plan_type") if key in row})
    if rows:
        result["rows"] = rows
    return result


def _write_private_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        if temp.exists():
            temp.unlink()


def refresh_snapshot(state_home=None, fetch_json=_fetch_json):
    cpa = resolve_cpa_config()
    generated_at = now_iso()
    previous = load_snapshot(state_home) or {}
    sources, models = {}, []
    if cpa["base_url"]:
        try:
            models = parse_catalog(fetch_json(cpa["base_url"] + "/models", cpa["api_key"]))
            sources["cpa"] = {"ok": True, "fetched_at": generated_at}
        except (OSError, ValueError, URLError) as exc:
            models = list(previous.get("models") or [])
            sources["cpa"] = {
                "ok": False,
                "fetched_at": generated_at,
                "error": type(exc).__name__,
                "used_cached_catalog": bool(models),
            }
    else:
        sources["cpa"] = {"ok": False, "fetched_at": generated_at, "error": "not_configured"}
    quota_url = os.environ.get("RUNTIME_AGENTS_QUOTA_WIDGET_URL", DEFAULT_QUOTA_URL)
    try:
        quota = _sanitized_quota(fetch_json(quota_url, None))
        sources["quota"] = {"ok": True, "fetched_at": generated_at, "provider": "openai", "data": quota}
    except (OSError, ValueError, URLError) as exc:
        sources["quota"] = {
            "ok": False,
            "fetched_at": generated_at,
            "provider": "openai",
            "error": type(exc).__name__,
        }
    snapshot = {"schema_version": 1, "generated_at": generated_at, "models": models, "sources": sources}
    path = snapshot_path(state_home)
    _write_private_json(path, snapshot)
    return snapshot


def load_snapshot(state_home=None):
    try:
        return json.loads(snapshot_path(state_home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def catalog_comparison(snapshot, configured=None):
    advertised = {f"local/{item['id']}" for item in (snapshot or {}).get("models", []) if item.get("id")}
    configured = set(configured if configured is not None else configured_local_models())
    return {
        "configured_models": sorted(configured),
        "advertised_models": sorted(advertised),
        "missing_from_opencode": sorted(advertised - configured),
        "stale_in_opencode": sorted(configured - advertised),
    }


def snapshot_freshness(snapshot, stale_after_seconds=DEFAULT_STALE_SECONDS):
    generated_at = (snapshot or {}).get("generated_at")
    age_seconds = None
    if generated_at:
        try:
            observed = datetime.fromisoformat(generated_at)
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (datetime.now(timezone.utc) - observed).total_seconds())
        except ValueError:
            pass
    return {
        "generated_at": generated_at,
        "age_seconds": age_seconds,
        "stale_after_seconds": stale_after_seconds,
        "stale": age_seconds is None or age_seconds > stale_after_seconds,
        "sources": (snapshot or {}).get("sources", {}),
    }


def frame_for_agent(config, agent, default="bounded_work"):
    agent_cfg = ((config or {}).get("agents") or {}).get(agent) if agent else None
    if isinstance(agent_cfg, dict) and agent_cfg.get("routing_frame") in DEFAULT_CANDIDATES:
        return agent_cfg["routing_frame"]
    return default


def _routing_candidates(config, frame, agent):
    routing = (config or {}).get("model_routing") or {}
    frames = routing.get("frames") or routing.get("candidates") or {}
    value = frames.get(frame) if isinstance(frames, dict) else None
    if agent and isinstance((routing.get("agents") or {}).get(agent), (list, dict)):
        value = (routing.get("agents") or {}).get(agent)
    if isinstance(value, dict):
        value = value.get("candidates") or value.get("models")
    candidates = list(value) if isinstance(value, list) else list(DEFAULT_CANDIDATES[frame])
    agent_cfg = ((config or {}).get("agents") or {}).get(agent) or {}
    configured_model = agent_cfg.get("model")
    if configured_model and isinstance(configured_model, str):
        candidates = [configured_model] + [m for m in candidates if m != configured_model]
    return list(dict.fromkeys(model for model in candidates if isinstance(model, str)))


def _is_openai(model, ownership):
    owner = str(ownership.get(model.removeprefix("local/"), "")).lower()
    if owner and owner != "unknown":
        return "openai" in owner
    return model.removeprefix("local/").startswith(("gpt-", "codex-", "o1-", "o3-"))


def _percentage(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().removesuffix("%"))
        except ValueError:
            return None
    return None


def openai_quota_policy(snapshot):
    source = ((snapshot or {}).get("sources") or {}).get("quota") or {}
    if not source.get("ok") or source.get("provider") != "openai":
        return {"state": "unknown", "reason": "openai_quota_unavailable"}
    data = source.get("data") or {}
    row_values = [
        value
        for value in (_percentage(row.get("weekly_left")) for row in data.get("rows", []) if isinstance(row, dict))
        if value is not None
    ]
    average = _percentage(data.get("weekly_avg_left"))
    if average is None:
        average = _percentage(data.get("weekly_left"))
    minimum = _percentage(data.get("weekly_min_left"))
    if minimum is None and row_values:
        minimum = min(row_values)
    exhausted = bool(data.get("limited") or data.get("exhausted"))
    if row_values and all(value <= 0 for value in row_values):
        exhausted = True
    if average is not None and average <= 0:
        exhausted = True
    if exhausted:
        state = "exhausted"
        reason = "openai_weekly_quota_exhausted"
    elif (average is not None and average <= 20) or (minimum is not None and minimum <= 5):
        state = "constrained"
        reason = "openai_weekly_quota_constrained"
    else:
        state = "healthy"
        reason = "openai_weekly_quota_healthy"
    return {"state": state, "reason": reason, "weekly_average_left": average, "weekly_minimum_left": minimum}


def load_cooldowns(state_home=None):
    try:
        payload = json.loads(cooldowns_path(state_home).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def active_cooldowns(state_home=None, now=None):
    current = now or datetime.now(timezone.utc)
    active = {}
    for model, entry in load_cooldowns(state_home).items():
        if not isinstance(entry, dict) or not entry.get("until"):
            continue
        try:
            until = datetime.fromisoformat(entry["until"])
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if until > current:
            active[model] = entry
    return active


def record_cooldown(model, reason, seconds=900, state_home=None, now=None):
    current = now or datetime.now(timezone.utc)
    from datetime import timedelta
    payload = active_cooldowns(state_home, current)
    payload[model] = {
        "reason": reason,
        "recorded_at": current.isoformat(),
        "until": (current + timedelta(seconds=max(1, int(seconds)))).isoformat(),
    }
    _write_private_json(cooldowns_path(state_home), payload)
    return payload[model]


def recommend(snapshot, frame, config=None, agent=None, state_home=None):
    if frame not in DEFAULT_CANDIDATES:
        raise ValueError(f"unknown frame: {frame}")
    candidates = _routing_candidates(config, frame, agent)
    advertised = {item["id"] for item in (snapshot or {}).get("models", []) if item.get("id")}
    ownership = {item["id"]: item.get("owned_by", "unknown") for item in (snapshot or {}).get("models", [])}
    quota_policy = openai_quota_policy(snapshot)
    deprecated = deprecated_local_models()
    cooldowns = active_cooldowns(state_home)
    viable, skipped, penalized = [], [], []
    for model in candidates:
        model_id = model.removeprefix("local/")
        if advertised and model_id not in advertised:
            skipped.append({"model": model, "reason": "missing_from_cpa_catalog"})
        elif model in deprecated:
            skipped.append({"model": model, "reason": "deprecated_in_opencode"})
        elif model in cooldowns:
            skipped.append({"model": model, "reason": "local_model_cooldown", "until": cooldowns[model].get("until")})
        elif quota_policy["state"] == "exhausted" and _is_openai(model, ownership):
            skipped.append({"model": model, "reason": quota_policy["reason"]})
        else:
            viable.append(model)
    if quota_policy["state"] == "constrained":
        openai_models = [model for model in viable if _is_openai(model, ownership)]
        if openai_models:
            penalized = [{"model": model, "reason": quota_policy["reason"]} for model in openai_models]
            viable = [model for model in viable if model not in openai_models] + openai_models
    return {
        "advisory_only": True,
        "frame": frame,
        "agent": agent,
        "selected_model": viable[0] if viable else None,
        "fallbacks": viable[1:],
        "skipped": skipped,
        "penalized": penalized,
        "quota_policy": quota_policy,
        "cooldowns": cooldowns,
        "data_freshness": snapshot_freshness(snapshot),
    }


def dispatch_preflight(config, agent, requested_model=None, state_home=None, refresh=True):
    routing = (config or {}).get("model_routing") or {}
    required = bool(routing.get("required"))
    agent_cfg = ((config or {}).get("agents") or {}).get(agent) or {}
    static_model = requested_model or agent_cfg.get("model") or ((config or {}).get("models") or {}).get("primary")
    if not required:
        return {
            "required": False,
            "explicit_override": bool(requested_model),
            "frame": frame_for_agent(config, agent),
            "selected_model": static_model,
            "fallbacks": [],
            "skipped": [],
            "reason": "model_routing_not_required",
        }
    frame = frame_for_agent(config, agent)
    if requested_model:
        snapshot = refresh_snapshot(state_home) if refresh else (load_snapshot(state_home) or refresh_snapshot(state_home))
        advertised = {f"local/{item['id']}" for item in snapshot.get("models", []) if item.get("id")}
        ownership = {item["id"]: item.get("owned_by", "unknown") for item in snapshot.get("models", []) if item.get("id")}
        quota_policy = openai_quota_policy(snapshot)
        skipped = []
        cpa_source = (snapshot.get("sources") or {}).get("cpa") or {}
        if not advertised and not cpa_source.get("ok"):
            skipped.append({"reason": "cpa_catalog_unavailable"})
        elif not advertised:
            skipped.append({"reason": "cpa_catalog_empty"})
        elif requested_model not in advertised:
            skipped.append({"model": requested_model, "reason": "missing_from_cpa_catalog"})
        if requested_model in deprecated_local_models():
            skipped.append({"model": requested_model, "reason": "deprecated_in_opencode"})
        if requested_model in active_cooldowns(state_home):
            skipped.append({"model": requested_model, "reason": "local_model_cooldown"})
        if quota_policy["state"] == "exhausted" and _is_openai(requested_model, ownership):
            skipped.append({"model": requested_model, "reason": quota_policy["reason"]})
        return {
            "required": True,
            "enforced": True,
            "advisory_only": False,
            "explicit_override": True,
            "frame": frame,
            "selected_model": requested_model if not skipped else None,
            "fallbacks": [],
            "skipped": skipped,
            "quota_policy": quota_policy,
            "data_freshness": snapshot_freshness(snapshot),
        }
    snapshot = refresh_snapshot(state_home) if refresh else (load_snapshot(state_home) or refresh_snapshot(state_home))
    cpa_source = (snapshot.get("sources") or {}).get("cpa") or {}
    if not snapshot.get("models"):
        return {
            "required": True,
            "explicit_override": False,
            "frame": frame,
            "selected_model": None,
            "fallbacks": [],
            "skipped": [{"reason": "cpa_catalog_unavailable" if not cpa_source.get("ok") else "cpa_catalog_empty"}],
            "data_freshness": snapshot_freshness(snapshot),
        }
    result = recommend(snapshot, frame, config, agent, state_home)
    return {**result, "required": True, "enforced": True, "advisory_only": False, "explicit_override": False}
