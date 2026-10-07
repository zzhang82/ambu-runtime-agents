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


if __name__ == "__main__":
    unittest.main()
