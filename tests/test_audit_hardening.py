import argparse
import importlib.metadata
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from runtime_agents import cli, execution_substrate, loop_engine


def make_test_db(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE session (
            id TEXT PRIMARY KEY, directory TEXT, agent TEXT, model TEXT,
            cost REAL, tokens_input INTEGER, tokens_output INTEGER,
            tokens_reasoning INTEGER, tokens_cache_read INTEGER,
            tokens_cache_write INTEGER, time_created INTEGER, time_updated INTEGER
        )""")
        for sid, directory, created, updated in rows:
            conn.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (sid, directory, "coder", '{"providerID":"test","id":"model"}',
                          1.0, 100, 20, 10, 0, 0, created, updated))


class AuditHardeningTests(unittest.TestCase):
    def test_autonomy_enforced_in_command(self):
        ro = execution_substrate.build_opencode_exec_command("test/model", "task", autonomy="read_only")
        rw = execution_substrate.build_opencode_exec_command("test/model", "task", autonomy="workspace_write")
        self.assertNotEqual(ro, rw)
        self.assertIn("oracle", ro)
        self.assertIn("build", rw)

    def test_find_latest_session_filters_by_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            db = home / ".local" / "share" / "opencode" / "opencode.db"
            make_test_db(db, [("ses_A", "/workspace/A", 100000, 101000),
                              ("ses_B", "/workspace/B", 101000, 102000)])
            with patch.object(Path, "home", return_value=home):
                got = cli.find_latest_opencode_session(100000, "/workspace/A")
            self.assertEqual(got, "ses_A")

    def test_find_latest_session_bounds_time(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            db = home / ".local" / "share" / "opencode" / "opencode.db"
            make_test_db(db, [("ses_old_task", "/workspace/A", 100000, 102000),
                              ("ses_much_later", "/workspace/A", 900000, 901000)])
            with patch.object(Path, "home", return_value=home):
                got = cli.find_latest_opencode_session(100000, "/workspace/A", end_ms=105000)
            self.assertEqual(got, "ses_old_task")

    def test_whitespace_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "report.md").write_text(" \n", encoding="utf-8")
            ok, err = loop_engine.check_eval_artifacts(root, ["report.md"])
            self.assertFalse(ok)
            self.assertIn("whitespace", err)

    def test_load_version_finds_ambu_runtime_agents(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            site = root / "site-packages"
            dist = site / "ambu_runtime_agents-1.5.1.dist-info"
            dist.mkdir(parents=True)
            (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: ambu-runtime-agents\nVersion: 1.5.1\n")
            with patch.object(cli, "VERSION_PATH", root / "nonexistent-version"), \
                 patch.object(importlib.metadata, "version", side_effect=lambda name: "1.5.1" if name == "ambu-runtime-agents" else None):
                got = cli.load_version()
            self.assertEqual(got, "1.5.1")

    def test_resume_preserves_contract_and_cwd(self):
        task = {
            "task_id": "old-task",
            "agent": "coder",
            "model": "test/model",
            "goal": "implement feature",
            "session_id": "ses_A",
            "workspace": None,
            "cwd": "/original/project",
            "mode": "iterate",
            "check": "python acceptance.py",
            "eval_artifacts": ["report.md"],
            "max_rounds": 3,
            "max_same_failure": 2,
            "approved_capabilities": [],
        }
        with patch.object(cli, "RUNS_DIR", Path("/unused")), \
             patch.object(cli, "latest_task", return_value=task), \
             patch.object(cli, "iterate_cmd", return_value=0) as mock_iterate:
            args = argparse.Namespace(task_id="old-task", model=None, prompt=None, json=True)
            rc = cli.resume_task_cmd(args)
            self.assertEqual(rc, 0)
            mock_iterate.assert_called_once()
            called_args = vars(mock_iterate.call_args.args[0])
            self.assertEqual(called_args["check"], "python acceptance.py")
            self.assertEqual(called_args["eval_artifacts"], ["report.md"])
            self.assertEqual(called_args["max_rounds"], 3)
            self.assertEqual(called_args["max_same_failure"], 2)
            self.assertEqual(called_args["cwd"], "/original/project")
            self.assertEqual(called_args["session_id"], "ses_A")

    def test_run_worker_timeout_survives_metadata_roundtrip(self):
        task_meta = {
            "task_id": "test-timeout-roundtrip",
            "agent": "coder",
            "model": "test/model",
            "goal": "implement timeout",
            "session_id": "ses_timeout",
            "workspace": None,
            "cwd": "/original/project",
            "mode": "run",
            "timeout": 91,
            "approved_capabilities": [],
        }
        with patch.object(cli, "RUNS_DIR", Path("/unused")), \
             patch.object(cli, "latest_task", return_value=task_meta), \
             patch.object(cli, "run_task", return_value=0) as mock_run:
            args = argparse.Namespace(task_id="test-timeout-roundtrip", model=None, prompt=None, json=True)
            cli.resume_task_cmd(args)
            mock_run.assert_called_once()
            resumed_args = vars(mock_run.call_args.args[0])
            self.assertEqual(resumed_args.get("timeout"), 91)

    def test_no_end_or_id_must_not_resume_arbitrary_later_session(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            db = home / ".local" / "share" / "opencode" / "opencode.db"
            make_test_db(db, [("later_unrelated", "/workspace/A", 900000, 901000)])
            task_meta = {
                "task_id": "unended-task",
                "agent": "coder",
                "model": "test/model",
                "goal": "unended",
                "session_id": None,
                "cwd": "/workspace/A",
                "started_at": "1970-01-01T00:01:40Z",
                "ended_at": None,
                "status": "running",
                "mode": "run",
            }
            with patch.object(cli, "RUNS_DIR", Path("/unused")), \
                 patch.object(cli, "latest_task", return_value=task_meta), \
                 patch.object(Path, "home", return_value=home):
                args = argparse.Namespace(task_id="unended-task", model=None, prompt=None, json=True)
                with self.assertRaises(SystemExit) as raised:
                    cli.resume_task_cmd(args)
                self.assertIn("No OpenCode session recorded", str(raised.exception))

    def test_interrupted_iteration_charges_dispatched_round(self):
        task_meta = {
            "task_id": "interrupted-iter",
            "agent": "coder",
            "model": "test/model",
            "goal": "fix acceptance",
            "session_id": "ses_round1",
            "workspace": None,
            "cwd": "/workspace/A",
            "mode": "iterate",
            "check": "python check.py",
            "eval_artifacts": [],
            "max_rounds": 3,
            "rounds": 1,
            "rounds_started": 2,
            "status": "cancelled",
        }
        with patch.object(cli, "RUNS_DIR", Path("/unused")), \
             patch.object(cli, "latest_task", return_value=task_meta), \
             patch.object(cli, "iterate_cmd", return_value=0) as mock_iterate:
            args = argparse.Namespace(task_id="interrupted-iter", model=None, prompt=None, json=True)
            cli.resume_task_cmd(args)
            mock_iterate.assert_called_once()
            called_args = vars(mock_iterate.call_args.args[0])
            # 3 max rounds minus 2 started rounds leaves 1
            self.assertEqual(called_args["max_rounds"], 1)

    def test_dispatch_does_not_guess_foreign_session_on_success(self):
        # Even if a foreign session exists in the DB within the time window,
        # execute_agent_attempts must not guess or adopt it on successful exit.
        agent_cfg = {"tool": "opencode", "autonomy": "workspace_write", "opencode_agent": "coder"}
        with patch.object(cli, "run_command", return_value={"returncode": 0, "stdout": "ok", "stderr": ""}), \
             patch.object(cli, "find_latest_opencode_session", return_value="ses_foreign"):
            attempts, final = cli.execute_agent_attempts(
                agent_cfg, "opencode", "test/model", "prompt", "workspace_write",
                fallback=False, timeout=10, session_id=None, fork=False,
            )
            self.assertIsNone(final.get("session_id"))
            self.assertIsNone(attempts[0].get("session_id"))

            # When continuing a known session without fork, preserve the known session
            attempts, final = cli.execute_agent_attempts(
                agent_cfg, "opencode", "test/model", "prompt", "workspace_write",
                fallback=False, timeout=10, session_id="ses_owned", fork=False,
            )
            self.assertEqual(final.get("session_id"), "ses_owned")
            self.assertEqual(attempts[0].get("session_id"), "ses_owned")

    def test_fork_execution_must_not_persist_parent_session(self):
        # When fork=True is passed, run_task must not backfill parent session_id into metadata
        agent_cfg = {"tool": "opencode", "autonomy": "workspace_write", "opencode_agent": "coder"}
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            with patch.object(cli, "RUNS_DIR", run_dir), \
                 patch.object(cli.model_catalog_mod, "dispatch_preflight", return_value={"selected_model": "test/model", "required": False}), \
                 patch.object(cli, "execute_agent_attempts", return_value=([{"attempt": 1, "stdout": "", "stderr": "", "returncode": 0}], {"attempt": 1, "stdout": "", "stderr": "", "returncode": 0, "model": "test/model"})):
                args = argparse.Namespace(
                    agent="coder", prompt=["test"], model="test/model", workspace=None,
                    approve=[], fallback=False, timeout=0, json=True,
                    session_id="ses_parent", fork=True,
                )
                rc = cli.run_task(args)
                self.assertEqual(rc, 0)
                meta = cli.load_json_file(list(run_dir.glob("*/metadata.json"))[0]) or {}
                self.assertIsNone(meta.get("session_id"))
                self.assertEqual(meta.get("continued_from_session"), "ses_parent")


if __name__ == "__main__":
    unittest.main()
