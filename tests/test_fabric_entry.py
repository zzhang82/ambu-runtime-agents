from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_agents import cli
from runtime_agents import fabric_entry
from runtime_agents import quota_watcher


FABRIC_BIN = shutil.which("contract-fabric") or str(Path.home() / ".local" / "bin" / "contract-fabric")
SOURCE_COMMIT = "e7750e7c0f9d63faadf067505e60ad5a3d147383"


def _fixture_files(root: Path) -> tuple[dict, dict, dict, Path, Path]:
    evidence = root / "workflow" / "observation.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"sanitized":true}\n', encoding="utf-8")
    receipt_path = root / "workflow" / "receipt.json"
    run_id = "quota-watcher:quota-test:202609101600"
    receipt = {
        "schema_version": 1,
        "workflow_id": "quota-watcher",
        "schedule_id": "quota-test",
        "occurrence_id": "quota-test:202609101600",
        "logical_run_id": run_id,
        "attempts": [{
            "attempt_id": "attempt-test",
            "started_at": "2026-09-10T16:00:01Z",
            "finished_at": "2026-09-10T16:00:02Z",
            "outcome": "completed",
        }],
        "status": "completed",
        "updated_at": "2026-09-10T16:00:02Z",
        "retry_disposition": "retry_not_needed",
        "next_due_at": "2026-09-10T16:01:00Z",
        "change_event_id": "event-test",
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    observation = {
        "schema_version": 1,
        "workflow_id": "quota-watcher",
        "observation_id": "observation-test",
        "schedule_id": "quota-test",
        "occurrence_id": receipt["occurrence_id"],
        "logical_run_id": run_id,
        "attempt_id": "attempt-test",
        "observed_at": "2026-09-10T16:00:01Z",
        "recorded_at": "2026-09-10T16:00:02Z",
        "collection_status": "fresh",
        "observation_freshness": "fresh",
    }
    schedule = {
        "workflow": "quota-watcher",
        "schedule_id": "quota-test",
        "cron": "* * * * *",
        "enabled": True,
    }
    return schedule, receipt, observation, evidence, receipt_path


class FabricEntryTests(unittest.TestCase):
    def test_unknown_mode_is_rejected_by_existing_cli_parser(self):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            ["python3", "-m", "runtime_agents.cli", "fabric", "run", "--mode", "automatic", "--dry-run"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid choice", result.stderr)

    def test_policy_rejection_happens_before_fabric_invocation(self):
        args = type("Args", (), {"mode": "local", "profile": None, "tool": None, "dry_run": False})()
        with patch.object(cli, "_fabric_guardrail_payload", return_value={"decision": "block", "rule_id": "test"}), patch.object(
            fabric_entry, "invoke", side_effect=AssertionError("Fabric must not run")
        ):
            with patch.object(cli, "print_json") as printed:
                result = cli.fabric_run_cmd(args)
        self.assertEqual(result, 2)
        self.assertEqual(printed.call_args.args[0]["status"], "block")

    def test_local_path_materializes_without_queue_write(self):
        with tempfile.TemporaryDirectory(prefix="fabric-entry-") as temp:
            root = Path(temp)
            schedule, receipt, observation, evidence, receipt_path = _fixture_files(root)
            state_home = root / "state"
            args = type(
                "Args",
                (),
                {
                    "mode": "local",
                    "workflow": "quota-watcher",
                    "profile": None,
                    "tool": None,
                    "dry_run": False,
                    "state_home": str(state_home),
                    "schedule_id": "quota-test",
                    "snapshot_root": str(root / "fabric"),
                    "cron": "* * * * *",
                    "max_attempts": 1,
                    "retry_backoff": 0.0,
                    "stale_attempt_seconds": 120.0,
                    "task_file": None,
                    "postgres_config": None,
                },
            )()
            observation["evidence_ref"] = str(evidence)
            workflow = {"status": "executed", "attempted": True, "receipt": receipt, "observation": observation}
            watcher_receipt = quota_watcher._receipt_path(
                quota_watcher._state_root(state_home), receipt["occurrence_id"]
            )
            watcher_receipt.parent.mkdir(parents=True, exist_ok=True)
            watcher_receipt.write_text(json.dumps(receipt), encoding="utf-8")
            with patch.dict(os.environ, {"RUNTIME_AGENTS_CONTRACT_FABRIC_BIN": FABRIC_BIN}, clear=False), patch.object(
                quota_watcher, "run_due", return_value=workflow
            ), patch.object(cli, "append_queue", side_effect=AssertionError("local Fabric must not write queue")):
                captured = []
                with patch.object(cli, "print_json", side_effect=captured.append):
                    result = cli.fabric_run_cmd(args)
            self.assertEqual(result, 0)
            output = captured[0]
            self.assertEqual(output["mode"], "local")
            self.assertEqual(output["admission"]["eligibility_pool"], "default")
            self.assertNotIn("task_id", output["admission"])
            self.assertEqual(output["fabric"]["provenance"]["schema_sha256"], fabric_entry.EXPECTED_SCHEMA_SHA256)

    def test_coordinated_path_never_appends_local_queue(self):
        with tempfile.TemporaryDirectory(prefix="fabric-coordinated-entry-") as temp:
            root = Path(temp)
            task_path = root / "task.json"
            config_path = root / "postgres.json"
            task_path.write_text(json.dumps({"task_id": "task-1"}), encoding="utf-8")
            config_path.write_text("{}", encoding="utf-8")
            args = type(
                "Args",
                (),
                {
                    "mode": "coordinated",
                    "workflow": "quota-watcher",
                    "profile": None,
                    "tool": None,
                    "dry_run": False,
                    "task_file": str(task_path),
                    "postgres_config": str(config_path),
                },
            )()
            admission = {"mode": "coordinated", "task_id": "task-1", "status": "queued", "provenance": {"schema_sha256": fabric_entry.EXPECTED_SCHEMA_SHA256, "spec_sha256": fabric_entry.EXPECTED_SPEC_SHA256}}
            with patch.object(fabric_entry, "invoke", return_value=admission), patch.object(
                cli, "append_queue", side_effect=AssertionError("coordinated Fabric must not write local queue")
            ):
                captured = []
                with patch.object(cli, "print_json", side_effect=captured.append):
                    result = cli.fabric_run_cmd(args)
            self.assertEqual(result, 0)
            self.assertEqual(captured[0]["local_queue"], "not_created")

    def test_source_drift_from_external_boundary_fails_closed(self):
        with patch.object(fabric_entry, "_executable", return_value=Path(FABRIC_BIN)):
            fake = {"provenance": {"schema_sha256": "0" * 64, "spec_sha256": fabric_entry.EXPECTED_SPEC_SHA256}}
            process = subprocess.CompletedProcess([], 0, json.dumps(fake), "")
            with patch("runtime_agents.fabric_entry.subprocess.run", return_value=process):
                with self.assertRaisesRegex(fabric_entry.FabricEntryError, "schema provenance"):
                    fabric_entry.invoke("inspect-local", {"snapshot_root": "/tmp", "logical_run_id": "run"})

    def test_inspect_without_snapshot_is_read_only(self):
        with tempfile.TemporaryDirectory(prefix="fabric-inspect-") as temp:
            with patch.dict(os.environ, {"RUNTIME_AGENTS_CONTRACT_FABRIC_BIN": FABRIC_BIN}, clear=False):
                result = fabric_entry.invoke(
                    "inspect-local",
                    {"snapshot_root": str(Path(temp) / "fabric"), "logical_run_id": "quota-watcher:missing"},
                )
            self.assertFalse(result["found"])
            self.assertEqual(result["snapshot_count"], 0)

    def test_coordinated_entry_requires_task_and_postgres_inputs(self):
        args = type(
            "Args",
            (),
            {
                "mode": "coordinated",
                "workflow": "quota-watcher",
                "profile": None,
                "tool": None,
                "dry_run": False,
                "task_file": None,
                "postgres_config": None,
            },
        )()
        captured = []
        with patch.object(cli, "print_json", side_effect=captured.append):
            result = cli.fabric_run_cmd(args)
        self.assertEqual(result, 1)
        self.assertEqual(captured[0]["status"], "failed")
        self.assertIn("task-file", captured[0]["error"])

    def test_coordinated_submission_failure_does_not_enqueue_local_work(self):
        with tempfile.TemporaryDirectory(prefix="fabric-submit-failure-") as temp:
            root = Path(temp)
            task_file = root / "task.json"
            task_file.write_text(json.dumps({"task_id": "task-1"}), encoding="utf-8")
            args = type(
                "Args",
                (),
                {
                    "mode": "coordinated",
                    "workflow": "quota-watcher",
                    "profile": None,
                    "tool": None,
                    "dry_run": False,
                    "task_file": str(task_file),
                    "postgres_config": str(root / "postgres.json"),
                },
            )()
            captured = []
            with patch.object(
                fabric_entry,
                "invoke",
                side_effect=fabric_entry.FabricEntryError("submit failed"),
            ), patch.object(cli, "append_queue", side_effect=AssertionError("queue write")), patch.object(
                cli, "print_json", side_effect=captured.append
            ):
                result = cli.fabric_run_cmd(args)
            self.assertEqual(result, 1)
            self.assertEqual(captured[0]["status"], "failed")
            self.assertIn("submit failed", captured[0]["error"])

    def test_local_execution_failure_is_reported_without_policy_rewrite(self):
        with tempfile.TemporaryDirectory(prefix="fabric-local-failure-") as temp:
            root = Path(temp)
            schedule, receipt, observation, _evidence, _receipt_path = _fixture_files(root)
            state_home = root / "state"
            args = type(
                "Args",
                (),
                {
                    "mode": "local",
                    "workflow": "quota-watcher",
                    "profile": None,
                    "tool": None,
                    "dry_run": False,
                    "state_home": str(state_home),
                    "schedule_id": "quota-test",
                    "snapshot_root": str(root / "fabric"),
                    "cron": "* * * * *",
                    "max_attempts": 1,
                    "retry_backoff": 0.0,
                    "stale_attempt_seconds": 120.0,
                    "task_file": None,
                    "postgres_config": None,
                },
            )()
            failed = dict(receipt, status="failed", failure_class="source_unavailable")
            workflow = {
                "status": "executed",
                "attempted": True,
                "receipt": failed,
                "observation": dict(observation, collection_status="unavailable", observation_freshness="unavailable"),
            }
            before = json.dumps(failed, sort_keys=True)
            captured = []
            with patch.object(quota_watcher, "run_due", return_value=workflow), patch.object(
                fabric_entry,
                "invoke",
                return_value={"admission": {}, "snapshot": {}, "inspection": {}},
            ), patch.object(cli, "print_json", side_effect=captured.append):
                result = cli.fabric_run_cmd(args)
            self.assertEqual(result, 1)
            self.assertEqual(captured[0]["status"], "failed")
            self.assertEqual(json.dumps(failed, sort_keys=True), before)

    def test_materialization_failure_does_not_rewrite_successful_workflow(self):
        with tempfile.TemporaryDirectory(prefix="fabric-materialize-failure-") as temp:
            root = Path(temp)
            schedule, receipt, observation, _evidence, _receipt_path = _fixture_files(root)
            state_home = root / "state"
            args = type(
                "Args",
                (),
                {
                    "mode": "local",
                    "workflow": "quota-watcher",
                    "profile": None,
                    "tool": None,
                    "dry_run": False,
                    "state_home": str(state_home),
                    "schedule_id": "quota-test",
                    "snapshot_root": str(root / "fabric"),
                    "cron": "* * * * *",
                    "max_attempts": 1,
                    "retry_backoff": 0.0,
                    "stale_attempt_seconds": 120.0,
                    "task_file": None,
                    "postgres_config": None,
                },
            )()
            workflow = {"status": "executed", "attempted": True, "receipt": receipt, "observation": observation}
            before = json.dumps(receipt, sort_keys=True)
            captured = []
            with patch.object(quota_watcher, "run_due", return_value=workflow), patch.object(
                fabric_entry,
                "invoke",
                side_effect=fabric_entry.FabricEntryError("materialization failed"),
            ), patch.object(cli, "print_json", side_effect=captured.append):
                result = cli.fabric_run_cmd(args)
            self.assertEqual(result, 1)
            self.assertEqual(captured[0]["status"], "failed")
            self.assertIn("materialization failed", captured[0]["error"])
            self.assertEqual(json.dumps(receipt, sort_keys=True), before)

    def test_fabric_process_boundary_removes_ambient_pythonpath(self):
        process = subprocess.CompletedProcess(
            [],
            0,
            json.dumps({"provenance": {"schema_sha256": fabric_entry.EXPECTED_SCHEMA_SHA256, "spec_sha256": fabric_entry.EXPECTED_SPEC_SHA256}}),
            "",
        )
        with patch.object(fabric_entry, "_executable", return_value=Path(FABRIC_BIN)), patch.dict(
            os.environ, {"PYTHONPATH": "/tmp/untrusted-source"}, clear=False
        ), patch("runtime_agents.fabric_entry.subprocess.run", return_value=process) as run:
            fabric_entry.invoke("inspect-local", {"snapshot_root": "/tmp", "logical_run_id": "run"})
        self.assertNotIn("PYTHONPATH", run.call_args.kwargs["env"])


if __name__ == "__main__":
    unittest.main()
