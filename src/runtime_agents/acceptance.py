"""Supervisor-owned, additive task acceptance. Never interprets worker claims as checks."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess
from pathlib import Path

from runtime_agents.state import atomic_write_json


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def local_path(root, name):
    require(isinstance(name, str) and bool(name), "file path must be nonempty")
    require(not Path(name).is_absolute(), "file path must be workspace-relative")
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "file path escapes workspace")
    return path


SCHEMA_KEYS = {"type", "properties", "required", "items", "enum", "minLength",
               "minItems", "additionalProperties"}
TYPES = {"object": dict, "array": list, "string": str, "integer": int,
         "number": (int, float), "boolean": bool, "null": type(None)}


def validate_schema(schema):
    require(isinstance(schema, dict), "schema must be an object")
    require(not set(schema) - SCHEMA_KEYS, "unsupported JSON schema keyword")
    require(isinstance(schema.get("type"), str) and schema["type"] in TYPES, "schema requires a supported type")
    if "properties" in schema:
        require(schema["type"] == "object" and isinstance(schema["properties"], dict), "invalid properties")
        for child in schema["properties"].values():
            validate_schema(child)
    if "required" in schema:
        require(schema["type"] == "object" and isinstance(schema["required"], list)
                and all(isinstance(x, str) for x in schema["required"]), "invalid required fields")
    if "items" in schema:
        require(schema["type"] == "array", "items requires array type")
        validate_schema(schema["items"])
    for key, kind in (("minLength", "string"), ("minItems", "array")):
        if key in schema:
            require(schema["type"] == kind and type(schema[key]) is int and schema[key] >= 0,
                    f"invalid {key}")
    if "additionalProperties" in schema:
        require(schema["type"] == "object" and type(schema["additionalProperties"]) is bool,
                "additionalProperties must be boolean")
    if "enum" in schema:
        require(isinstance(schema["enum"], list) and bool(schema["enum"]), "enum must be nonempty")


def matches_schema(value, schema):
    kind = schema["type"]
    require(isinstance(value, TYPES[kind]) and not
            (kind in {"integer", "number"} and isinstance(value, bool)), f"expected {kind}")
    if "enum" in schema:
        require(value in schema["enum"], "value outside enum")
    if kind == "object":
        require(all(k in value for k in schema.get("required", [])), "missing required JSON field")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(not set(value) - set(props), "unexpected JSON field")
        for key, child in props.items():
            if key in value:
                matches_schema(value[key], child)
    if kind == "array":
        require(len(value) >= schema.get("minItems", 0), "too few array items")
        if "items" in schema:
            for item in value:
                matches_schema(item, schema["items"])
    if kind == "string":
        require(len(value) >= schema.get("minLength", 0), "string too short")


def permission_key(value):
    require(isinstance(value, dict) and set(value) == {"operation", "target"},
            "permission requires exactly operation and target")
    require(all(isinstance(v, str) and v.strip() for v in value.values()), "invalid permission")
    return value["operation"], value["target"]


@dataclass(frozen=True)
class FrozenContract:
    """Canonical bytes are immutable; callers receive detached decoded copies."""
    document: str
    fingerprint: str

    def payload(self):
        return {**json.loads(self.document), "contract_fingerprint": self.fingerprint}


def freeze(data, cwd):
    require(isinstance(data, dict), "contract must be a JSON object")
    data = json.loads(canonical(data))
    claimed = data.pop("contract_fingerprint", None)
    required = {"contract_version", "result_type", "required_outputs", "required_checks",
                "required_permissions", "validation_rules"}
    require(set(data) == required, "contract requires exactly the documented fields")
    require(type(data["contract_version"]) is int and data["contract_version"] == 1,
            "unsupported contract version")
    require(isinstance(data["result_type"], str) and data["result_type"] in {"implementation", "review", "extraction", "research"},
            "unsupported result type")
    for name in ("required_outputs", "required_checks", "required_permissions"):
        require(isinstance(data[name], list), f"{name} must be a list")
    require(data["required_outputs"] or data["required_checks"], "contract has no acceptance criteria")
    ids = set()
    for output in data["required_outputs"]:
        require(isinstance(output, dict) and not set(output) -
                {"id", "source", "path", "equals", "nonempty", "schema"}, "unsupported output rule")
        require(isinstance(output.get("id"), str) and bool(output["id"])
                and output["id"] not in ids, "missing or duplicate criterion id")
        ids.add(output["id"])
        require(isinstance(output.get("source"), str) and output["source"] in {"file", "stdout"}, "invalid output source")
        if output["source"] == "file":
            local_path(cwd, output.get("path"))
        else:
            require("path" not in output, "stdout output cannot have path")
        if "schema" in output:
            validate_schema(output["schema"])
        if "equals" in output:
            require(isinstance(output["equals"], str), "equals must be text")
        if "nonempty" in output:
            require(type(output["nonempty"]) is bool, "nonempty must be boolean")
        if data["result_type"] == "extraction":
            require("schema" in output, "extraction requires a schema")
    if data["result_type"] != "implementation":
        require(bool(data["required_outputs"]), "structured task requires output")
    else:
        require(data["required_checks"] or any(x["source"] == "file" for x in data["required_outputs"]),
                "implementation requires a file or check")
    for check in data["required_checks"]:
        require(isinstance(check, dict) and not set(check) - {"id", "command", "timeout", "inputs"},
                "unsupported check rule")
        require(isinstance(check.get("id"), str) and bool(check["id"]) and check["id"] not in ids,
                "missing or duplicate criterion id")
        ids.add(check["id"])
        if "command" in check:
            require(isinstance(check["command"], str) and bool(check["command"].strip()), "invalid command")
        require(type(check.get("timeout", 300)) is int and check.get("timeout", 300) >= 0,
                "check timeout must be nonnegative seconds")
        require(isinstance(check.get("inputs", {}), dict), "check inputs must be path/hash mapping")
        for path, sha in check.get("inputs", {}).items():
            local_path(cwd, path)
            require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha), "invalid check input digest")
    rules = data["validation_rules"]
    require(isinstance(rules, dict) and not set(rules) - {"optional_permissions", "manual_review"},
            "unsupported validation rule")
    require(type(rules.get("manual_review", False)) is bool, "manual_review must be boolean")
    require(isinstance(rules.get("optional_permissions", []), list), "optional_permissions must be a list")
    required_keys = {permission_key(p) for p in data["required_permissions"]}
    optional_keys = {permission_key(p) for p in rules.get("optional_permissions", [])}
    require(not required_keys & optional_keys, "permission cannot be both required and optional")
    document = canonical(data)
    fingerprint = digest(document.encode())
    require(claimed is None or claimed == fingerprint, "contract fingerprint mismatch")
    return FrozenContract(document, fingerprint)


def from_args(args, cwd, *, iterate=False):
    inherited = getattr(args, "frozen_acceptance_contract", None)
    path = getattr(args, "acceptance_contract", None)
    if inherited is not None:
        return freeze(inherited, cwd)
    if path:
        return freeze(json.loads(Path(path).read_text(encoding="utf-8")), cwd)
    if iterate:
        timeout = getattr(args, "check_timeout", None)
        checks = ([{"id": "iterate-check", "command": args.check,
                    "timeout": 300 if timeout is None else timeout}] if args.check else [])
        paths = [p.strip() for p in (getattr(args, "eval_artifact", []) or []) if p and p.strip()]
        paths = [str(Path(p).relative_to(cwd.resolve()))
                 if Path(p).is_absolute() and Path(p).is_relative_to(cwd.resolve()) else p for p in paths]
        outputs = [{"id": f"artifact-{i}", "source": "file", "path": p, "nonempty": True}
                   for i, p in enumerate(paths)]
        return freeze({"contract_version": 1, "result_type": "implementation",
                       "required_outputs": outputs, "required_checks": checks,
                       "required_permissions": [], "validation_rules": {}}, cwd)
    return None


def policy_text(contract):
    if contract is None:
        return ""
    return canonical(contract.payload())


def worker_instructions(contract):
    if contract is None:
        return ""
    return "\n\nSupervisor acceptance contract (read-only criteria; not permission grants):\n" + canonical(contract.payload())


def unknown_fields():
    return {"deliverable_status": "unknown", "acceptance_status": "unknown",
            "acceptance_reason": "No supervisor acceptance contract", "contract_fingerprint": None}


def view_fields(record):
    if not record.get("acceptance_contract"):
        return unknown_fields()
    return {k: record.get(k, v) for k, v in unknown_fields().items()}


class Acceptance:
    def __init__(self, contract, task_id, cwd, run_dir, runner):
        self.contract = contract
        self.task_id = task_id
        self.cwd = Path(cwd)
        self.run_dir = Path(run_dir)
        self.runner = runner
        self.history = []
        self.denials = []
        self.integrity_conflict = False
        self.result = None
        if contract:
            atomic_write_json(self.run_dir / "acceptance-contract.json", contract.payload())

    def fields(self):
        if self.contract is None:
            return unknown_fields()
        result = self.result or {"deliverable_status": "unknown", "status": "not_run",
                                 "reason": "Acceptance not evaluated"}
        fields = {"acceptance_contract": self.contract.payload(),
                  "contract_fingerprint": self.contract.fingerprint,
                  "deliverable_status": result["deliverable_status"],
                  "acceptance_status": result["status"], "acceptance_reason": result["reason"]}
        if self.result:
            fields["acceptance"] = self.result
        return fields

    def record(self, criterion, attempt, validator):
        return {"task_id": self.task_id, "attempt": attempt, "criterion_id": criterion,
                "contract_fingerprint": self.contract.fingerprint, "contract_version": 1,
                "validator": validator, "validator_version": 1, "executed": False,
                "returncode": None, "started_at": now(), "ended_at": now(),
                "status": "not_run", "reason": "Not executed", "evidence_ref": None}

    def save_evidence(self, label, data):
        directory = self.run_dir / "acceptance-evidence"
        directory.mkdir(exist_ok=True)
        ref = f"acceptance-evidence/{label}"
        (self.run_dir / ref).write_bytes(data)
        return ref

    def capture_denials(self, attempts, round_num=0):
        if not self.contract:
            return
        contract = self.contract.payload()
        required = {permission_key(p) for p in contract["required_permissions"]}
        optional = {permission_key(p) for p in contract["validation_rules"].get("optional_permissions", [])}
        native = re.compile(r"permission requested:\s*([\w-]+)\s*\((.*?)\);\s*auto-rejecting")
        for attempt in attempts:
            ordinal = f"{round_num}:{attempt.get('attempt', 1)}"
            for stream in ("stdout", "stderr"):
                text = attempt.get(stream) or ""
                text = re.sub(r"\x1b\[[0-9;]*m", "", text)
                last_native_line = None
                for line_no, line in enumerate(text.splitlines(), 1):
                    match = native.search(line) if stream == "stderr" else None
                    # OpenCode emits a companion rejection message after its native
                    # request and tool-error line. This is the same denial, not a
                    # second operation with unknown necessity.
                    if (stream == "stderr" and last_native_line is not None
                            and line_no - last_native_line <= 2
                            and line.strip() == "Error: The user rejected permission to use this specific tool call."):
                        last_native_line = None
                        continue
                    if not match and not re.search(r"permission.{0,80}(denied|reject)|(?:denied|reject).{0,80}permission", line, re.I):
                        continue
                    last_native_line = line_no if match else None
                    pair = match.groups() if match else None
                    necessity = "required" if pair in required else "optional" if pair in optional else "unresolved"
                    record = self.record("permission", ordinal, "native-denial-parser" if match else "denial-observation")
                    record.update(executed=True, status="failed", necessity=necessity,
                                  operation=pair[0] if pair else None, target=pair[1] if pair else None,
                                  reason="Observed denial; necessity from exact frozen declaration" if match else "Denial necessity unavailable",
                                  stream=stream, line=line_no, returncode=attempt.get("returncode"))
                    record["evidence_ref"] = self.save_evidence(f"denial-{len(self.denials)}.txt", line.encode())
                    self.denials.append(record)

    def policy_denials(self, capabilities):
        if not self.contract:
            return
        for cap in capabilities:
            record = self.record("permission", "policy", "approval-gate")
            record.update(executed=True, status="failed", necessity="required", operation=cap,
                          reason="Existing mandatory policy gate blocked execution")
            record["evidence_ref"] = self.save_evidence(f"policy-{len(self.denials)}.json", canonical(record).encode())
            self.denials.append(record)

    def output(self, output, attempt, stdout, index):
        record = self.record(output["id"], attempt, "output-" + self.contract.payload()["result_type"])
        record["executed"] = True
        try:
            if output["source"] == "file":
                path = local_path(self.cwd, output["path"])
                record["artifact"] = output["path"]
                if not path.exists():
                    record.update(status="missing", reason="Required file does not exist")
                    return record
                require(path.is_file(), "Required output is not a regular file")
                data = path.read_bytes()
            else:
                if stdout is None:
                    record.update(status="unknown", executed=False, reason="Worker stdout unavailable")
                    return record
                data = stdout.encode()
                if not data:
                    record.update(status="missing", reason="Required stdout result missing")
                    return record
            record["sha256"] = digest(data)
            record["evidence_ref"] = self.save_evidence(f"{len(self.history)}-output-{index}.bin", data)
            if output.get("nonempty"):
                require(bool(data.strip()), "Required output empty")
            if "equals" in output:
                require(data == output["equals"].encode(), "Output does not equal declared value")
            result_type = self.contract.payload()["result_type"]
            if "schema" in output or result_type != "implementation":
                value = json.loads(data.decode("utf-8"))
                if "schema" in output:
                    matches_schema(value, output["schema"])
                if result_type == "review":
                    require(isinstance(value, dict), "Review must be an object")
                    findings = value.get("findings")
                    require(isinstance(findings, list), "Review requires findings array")
                    require((value.get("verdict") == "no_findings" and not findings) or
                            (value.get("verdict") == "findings" and bool(findings)), "Invalid review verdict/findings")
                    require(all((isinstance(f, str) and bool(f.strip())) or
                                (isinstance(f, dict) and bool(f)) for f in findings), "Invalid finding")
                elif result_type == "research":
                    require(isinstance(value, dict) and isinstance(value.get("answer"), str)
                            and bool(value["answer"].strip()), "Research requires answer")
                    refs = value.get("evidence")
                    require(isinstance(refs, list) and bool(refs) and
                            all(isinstance(r, str) and bool(r.strip()) for r in refs), "Research evidence missing or invalid")
                    require(isinstance(value.get("limitations"), list) and
                            all(isinstance(x, str) for x in value["limitations"]), "Research requires explicit limitations")
            record.update(status="satisfied", reason="Declared output rules satisfied")
        except (ValueError, UnicodeError) as exc:
            record.update(status="invalid", reason=str(exc))
        except OSError as exc:
            record.update(status="unknown", reason=f"Output evidence unavailable: {type(exc).__name__}")
        finally:
            record["ended_at"] = now()
        return record

    def check(self, check, attempt, index, execute, observed):
        record = self.record(check["id"], attempt, "shell-check")
        record["definition_fingerprint"] = digest(canonical(check).encode())
        command = check.get("command")
        record["command"] = command
        if not execute or not command:
            return record
        try:
            for path, sha in check.get("inputs", {}).items():
                require(digest(local_path(self.cwd, path).read_bytes()) == sha, "Declared check input changed")
            result = observed.get(command) if command in observed else self.runner(command, self.cwd, check.get("timeout", 300))
            record.update(executed=True, returncode=result["returncode"],
                          started_at=result.get("started_at", record["started_at"]), ended_at=result.get("ended_at", now()),
                          status="passed" if result["returncode"] == 0 else "failed",
                          reason="Check exited zero" if result["returncode"] == 0 else "Check exited nonzero")
            record["artifact_fingerprints"] = self.artifact_fingerprints()
        except subprocess.TimeoutExpired as exc:
            result = {"stdout": str(exc.stdout or ""), "stderr": "check timeout", "returncode": 124}
            record.update(executed=True, status="failed", reason="Check timed out", returncode=124, ended_at=now())
        except (OSError, ValueError) as exc:
            result = {"error": str(exc)}
            record.update(status="unknown", reason=f"Check evidence unavailable: {exc}", ended_at=now())
        record["evidence_ref"] = self.save_evidence(f"{len(self.history)}-check-{index}.json", canonical(result).encode())
        return record

    def artifact_fingerprints(self):
        fingerprints = {}
        for output in self.contract.payload()["required_outputs"]:
            if output["source"] == "file":
                try:
                    fingerprints[output["id"]] = digest(local_path(self.cwd, output["path"]).read_bytes())
                except (OSError, ValueError):
                    fingerprints[output["id"]] = None
        return fingerprints

    def check_input_error(self, command):
        """Gate the existing iterate check before it can execute altered inputs."""
        if not self.contract:
            return None
        try:
            for check in self.contract.payload()["required_checks"]:
                if check.get("command") == command:
                    for path, sha in check.get("inputs", {}).items():
                        require(digest(local_path(self.cwd, path).read_bytes()) == sha, "Declared check input changed")
        except (OSError, ValueError) as exc:
            return str(exc)
        return None

    def check_timeout(self, command, fallback):
        limits = [c.get("timeout", 300) for c in self.contract.payload()["required_checks"]
                  if c.get("command") == command] if self.contract else []
        if not limits:
            return fallback
        positive = [limit for limit in limits if limit > 0]
        return min(positive) if positive else 0

    def evaluate(self, attempt, *, stdout=None, execute=True, observed=None):
        if not self.contract:
            return self.fields()
        contract = self.contract.payload()
        saved = self.run_dir / "acceptance-contract.json"
        try:
            self.integrity_conflict |= json.loads(saved.read_text()) != contract
        except (ValueError, OSError):
            self.integrity_conflict = True
        # Restore only this execution's supervisor-owned record, never worker criteria.
        atomic_write_json(saved, contract)
        checks = [self.check(c, attempt, i, execute, observed or {}) for i, c in enumerate(contract["required_checks"])]
        outputs = [self.output(o, attempt, stdout, i) for i, o in enumerate(contract["required_outputs"])]
        final_hashes = {o["criterion_id"]: o.get("sha256") for o in outputs}
        changed_after_check = any(
            any(final_hashes.get(key) != sha for key, sha in c.get("artifact_fingerprints", {}).items())
            for c in checks if c["status"] == "passed")
        research_judgment_unavailable = contract["result_type"] == "research" and any(
            "equals" not in output
            and "enum" not in output.get("schema", {})
            and "enum" not in output.get("schema", {}).get("properties", {}).get("answer", {})
            for output in contract["required_outputs"])
        states = {o["status"] for o in outputs}
        deliverable = next((s for s in ("invalid", "missing", "unknown") if s in states), "satisfied")
        status, reason = "passed", "All declared criteria satisfied by supervisor evidence"
        if deliverable in {"missing", "invalid"}:
            status, reason = "failed", "Required output " + deliverable
        elif any(c["status"] == "failed" for c in checks):
            status, reason = "failed", "Required check failed"
        elif any(d["necessity"] == "required" for d in self.denials):
            status, reason = "failed", "Required operation denied"
        elif self.integrity_conflict or changed_after_check or any(d["necessity"] == "unresolved" for d in self.denials):
            status, reason = "needs_review", "Contract/evidence integrity conflict or unresolved denial"
        elif any(c["status"] == "not_run" for c in checks):
            status, reason = "not_run", "Required verification not executed"
        elif deliverable == "unknown" or any(c["status"] == "unknown" for c in checks):
            status, reason = "unknown", "Required evidence unavailable"
        elif contract["validation_rules"].get("manual_review"):
            status, reason = "needs_review", "Contract requires semantic review"
        elif research_judgment_unavailable:
            status, reason = "needs_review", "Research structure verified; substantive answer requires judgment"
        evaluation = {"attempt": attempt, "outputs": outputs, "checks": checks,
                      "status": status, "reason": reason, "timestamp": now()}
        self.history.append(evaluation)
        self.result = {"task_id": self.task_id, "contract_fingerprint": self.contract.fingerprint,
                       "contract_version": 1, "deliverable_status": deliverable, "status": status,
                       "reason": reason, "outputs": outputs, "checks": checks,
                       "permission_blocks": self.denials, "evaluations": list(self.history)}
        atomic_write_json(self.run_dir / "acceptance.json", self.result)
        return self.fields()
