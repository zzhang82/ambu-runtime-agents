import json
import os
import subprocess
import threading
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def config_home():
    return Path(os.environ.get("RUNTIME_AGENTS_CONFIG_HOME", str(Path.home() / ".config" / "runtime-agents"))).expanduser()


CONFIG_PATH = config_home() / "agents.yaml"


class AMBAdapter:
    def __init__(self, config=None):
        self.config = config or self.load_config()
        self.mode = self.config.get("mode", "mcp_stdio")

    @staticmethod
    def load_config():
        if yaml is None:
            return {"mode": "missing_yaml"}
        if not CONFIG_PATH.exists():
            return {"mode": "missing_config"}
        data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        return data.get("amb") or {"mode": "missing_amb_config"}

    def health(self):
        if self.mode != "mcp_stdio":
            return {"ok": False, "mode": self.mode, "error": f"unsupported AMB mode: {self.mode}"}
        missing = []
        if not self.config.get("command"):
            missing.append("command")
        if missing:
            return {"ok": False, "mode": self.mode, "error": f"missing config fields: {','.join(missing)}"}
        try:
            tools = self.call_tool("tools/list", {}, method_is_tool=False)
            names = []
            response = tools.get("response") if tools.get("ok") else {}
            for tool in response.get("tools", []) if isinstance(response, dict) else []:
                if isinstance(tool, dict) and tool.get("name"):
                    names.append(tool["name"])
            return {"ok": tools.get("ok", False), "mode": self.mode, "tools": names, "error": tools.get("error")}
        except Exception as exc:
            return {"ok": False, "mode": self.mode, "error": str(exc)}

    def store(self, namespace, kind, content, tags=None, actor=None, source_app=None,
              source_client=None, source_model=None, client_session_id=None,
              client_workspace=None, client_transport=None, session_id=None,
              correlation_id=None, title=None):
        args = {
            "namespace": namespace,
            "kind": kind,
            "content": json.dumps(content) if not isinstance(content, str) else content,
            "tags": tags or [],
            "actor": actor,
            "source_app": source_app,
            "source_client": source_client,
            "source_model": source_model,
            "client_session_id": client_session_id,
            "client_workspace": client_workspace,
            "client_transport": client_transport or "stdio",
            "session_id": session_id,
            "correlation_id": correlation_id,
            "title": title,
        }
        args = {k: v for k, v in args.items() if v is not None}
        result = self.call_tool("store", args)
        if not result.get("ok"):
            return result
        payload = result.get("response") or {}
        return {
            "ok": True,
            "mode": self.mode,
            "tool": "store",
            "id": payload.get("id"),
            "stored": payload.get("stored"),
            "duplicate": payload.get("duplicate", False),
            "duplicate_of": payload.get("duplicate_of"),
            "response": payload,
            "error": None,
        }

    def recall(self, namespace, query, limit=5, kind="memory"):
        return self.call_tool("recall", {"namespace": namespace, "query": query, "limit": limit, "kind": kind})

    def call_tool(self, tool_name, arguments, method_is_tool=True):
        if self.mode != "mcp_stdio":
            return {"ok": False, "mode": self.mode, "tool": tool_name, "error": f"unsupported AMB mode: {self.mode}"}
        command = self.config.get("command")
        if not command:
            return {"ok": False, "mode": self.mode, "tool": tool_name, "error": "AMB command is not configured"}
        cmd = [command] + list(self.config.get("args") or [])
        env = os.environ.copy()
        env.update(self.config.get("env") or {})
        cwd = self.config.get("cwd") or None
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            return {"ok": False, "mode": self.mode, "tool": tool_name, "error": f"failed to launch AMB stdio server: {exc}"}

        stderr_chunks = []
        def drain_stderr():
            try:
                for line in proc.stderr:
                    stderr_chunks.append(line)
            except Exception:
                pass
        thread = threading.Thread(target=drain_stderr, daemon=True)
        thread.start()

        next_id = 1
        def send(method, params=None):
            nonlocal next_id
            rid = next_id
            next_id += 1
            msg = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params is not None:
                msg["params"] = params
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            return rid

        def recv(rid, timeout_seconds=30):
            # stdout readline is blocking; process timeout is handled by caller wait/kill on errors.
            while True:
                line = proc.stdout.readline()
                if not line:
                    raise RuntimeError("AMB stdio server closed stdout")
                data = json.loads(line)
                if data.get("id") == rid:
                    if "error" in data:
                        raise RuntimeError(json.dumps(data["error"], sort_keys=True))
                    return data.get("result") or {}

        try:
            init_id = send("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "runtime-agents", "version": "0.6.1"},
            })
            recv(init_id)
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
            proc.stdin.flush()
            if method_is_tool:
                rid = send("tools/call", {"name": tool_name, "arguments": arguments})
                raw = recv(rid)
                response = self._extract_tool_payload(raw)
            else:
                rid = send(tool_name, arguments or {})
                response = recv(rid)
            return {"ok": True, "mode": self.mode, "tool": tool_name, "response": response, "error": None}
        except Exception as exc:
            return {"ok": False, "mode": self.mode, "tool": tool_name, "error": str(exc), "stderr": "".join(stderr_chunks[-20:])}
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    @staticmethod
    def _extract_tool_payload(raw):
        if isinstance(raw, dict) and raw.get("structuredContent") is not None:
            return raw.get("structuredContent")
        content = raw.get("content") if isinstance(raw, dict) else None
        if isinstance(content, list) and content:
            text = content[0].get("text") if isinstance(content[0], dict) else None
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"text": text}
        return raw
