import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

from runtime_agents import model_catalog
from runtime_agents import quota_watcher as watcher


UTC = dt.timezone.utc


def quota_payload(*, average="80%", minimum="70%", exhausted=False):
    return {
        "weekly_avg_left": average,
        "weekly_min_left": minimum,
        "limited": exhausted,
        "exhausted": exhausted,
        "rows": [{"weekly_left": minimum, "plan_type": "review"}],
        "accounts_label": "person@example.test",
        "access_token": "must-not-be-persisted",
    }


class QuotaWatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quota-watcher-")
        self.state_home = Path(self.temp.name)
        self.schedule = {"workflow": watcher.WORKFLOW_ID, "schedule_id": "quota-pilot", "cron": "* * * * *", "enabled": True}
        self.base_when = dt.datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

    def tearDown(self):
        self.temp.cleanup()

    def collector(self, quota=None, models=None, failures=None):
        quota = quota if quota is not None else quota_payload()
        models = models if models is not None else [{"id": "gpt-5", "owned_by": "openai"}]
        failures = failures if failures is not None else {}

        def fetch(url, _api_key):
            kind = "cpa" if url.endswith("/models") else "quota"
            pending = failures.get(kind)
            if pending:
                failure = pending.pop(0)
                if failure is not None:
                    raise failure
            return {"data": models} if kind == "cpa" else quota

        return fetch

    def collector_env(self):
        return patch.object(
            model_catalog,
            "resolve_cpa_config",
            return_value={"base_url": "http://cpa.test/v1", "api_key": "not-written"},
        ), patch.dict(os.environ, {"RUNTIME_AGENTS_QUOTA_WIDGET_URL": "http://quota.test/widget"}, clear=False)

    def run_occurrence(self, *, fetch, when=None, **kwargs):
        with self.collector_env()[0], self.collector_env()[1]:
            return watcher.execute_occurrence(
                self.schedule,
                state_home=self.state_home,
                when=when or self.base_when,
                fetch_json=fetch,
                sleep=lambda _seconds: None,
                **kwargs,
            )

    def test_same_normalized_state_emits_one_event_but_keeps_two_receipts(self):
        fetch = self.collector()
        first = self.run_occurrence(fetch=fetch, when=self.base_when)
        second = self.run_occurrence(fetch=fetch, when=self.base_when + dt.timedelta(minutes=1))
        self.assertTrue(first["attempted"])
        self.assertTrue(second["attempted"])
        events = watcher._read_jsonl(self.state_home / watcher.STATE_DIR_NAME / watcher.EVENTS_NAME)
        observations = watcher._read_jsonl(self.state_home / watcher.STATE_DIR_NAME / watcher.OBSERVATIONS_NAME)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(observations), 2)
        self.assertNotEqual(first["receipt"]["occurrence_id"], second["receipt"]["occurrence_id"])

    def test_unknown_and_exhausted_are_distinct_states(self):
        first = self.run_occurrence(fetch=self.collector(quota=quota_payload(average=None, minimum=None)), when=self.base_when)
        second = self.run_occurrence(fetch=self.collector(quota=quota_payload(average="0%", minimum="0%", exhausted=True)), when=self.base_when + dt.timedelta(minutes=1))
        self.assertEqual(first["receipt"]["quota_state"], "unknown")
        self.assertEqual(second["receipt"]["quota_state"], "exhausted")
        self.assertNotEqual(first["receipt"]["state_fingerprint"], second["receipt"]["state_fingerprint"])

    def test_stale_cached_snapshot_is_not_reported_as_fresh(self):
        fetch = self.collector(failures={"cpa": [], "quota": []})
        self.run_occurrence(fetch=fetch, when=self.base_when)
        failing = self.collector(failures={"cpa": [URLError("offline")], "quota": [URLError("offline")]})
        result = self.run_occurrence(fetch=failing, when=self.base_when + dt.timedelta(minutes=1), max_attempts=1)
        observation = result["observation"]
        self.assertEqual(observation["collection_status"], "stale")
        self.assertEqual(observation["observation_freshness"], "stale")
        self.assertEqual(observation["normalized"]["quota_source"], "cached")

    def test_transient_unavailable_retries_with_new_attempt_and_succeeds(self):
        failures = {"cpa": [URLError("offline")], "quota": [URLError("offline")]}
        fetch = self.collector(failures=failures)
        result = self.run_occurrence(fetch=fetch, when=self.base_when, max_attempts=2)
        receipt = result["receipt"]
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["retry_disposition"], "retry_succeeded")
        self.assertEqual(len(receipt["attempts"]), 2)
        self.assertEqual(receipt["attempts"][0]["outcome"], "retryable_failure")
        self.assertEqual(receipt["attempts"][1]["outcome"], "completed")
        self.assertEqual(receipt["logical_run_id"], f"{watcher.WORKFLOW_ID}:{receipt['occurrence_id']}")
        self.assertNotEqual(receipt["attempts"][0]["attempt_id"], receipt["attempts"][1]["attempt_id"])

    def test_malformed_response_is_terminal_and_not_mislabelled_as_quota_state(self):
        failures = {"cpa": [ValueError("bad json")], "quota": [ValueError("bad json")]}
        result = self.run_occurrence(fetch=self.collector(failures=failures), when=self.base_when, max_attempts=1)
        receipt = result["receipt"]
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["retry_disposition"], "terminal_failure")
        self.assertEqual(len(receipt["attempts"]), 1)
        self.assertEqual(receipt["attempts"][0]["failure_class"], "ValueError")

    def test_duplicate_occurrence_does_not_collect_twice(self):
        calls = []
        fetch = self.collector()

        def counted(url, key):
            calls.append(url)
            return fetch(url, key)

        first = self.run_occurrence(fetch=counted, when=self.base_when)
        second = self.run_occurrence(fetch=counted, when=self.base_when)
        self.assertTrue(first["attempted"])
        self.assertFalse(second["attempted"])
        self.assertEqual(second["status"], "duplicate")
        self.assertEqual(len(calls), 2)

    def test_in_progress_occurrence_is_not_concurrently_reexecuted(self):
        root = watcher._state_root(self.state_home)
        occurrence_id = f"{self.schedule['schedule_id']}:{watcher.schedules.due_window_id(self.base_when)}"
        logical_run_id = f"{watcher.WORKFLOW_ID}:{occurrence_id}"
        watcher._claim_occurrence(
            root=root,
            schedule_id=self.schedule["schedule_id"],
            occurrence_id=occurrence_id,
            logical_run_id=logical_run_id,
            started_at=watcher.now_iso(),
            stale_attempt_seconds=120,
        )
        result = self.run_occurrence(fetch=self.collector(), when=self.base_when)
        self.assertEqual(result["status"], "in_progress")
        self.assertFalse(result["attempted"])

    def test_stale_running_attempt_is_marked_interrupted_before_restart(self):
        root = watcher._state_root(self.state_home)
        occurrence_id = f"{self.schedule['schedule_id']}:{watcher.schedules.due_window_id(self.base_when)}"
        logical_run_id = f"{watcher.WORKFLOW_ID}:{occurrence_id}"
        receipt, _attempt, _claimed = watcher._claim_occurrence(
            root=root,
            schedule_id=self.schedule["schedule_id"],
            occurrence_id=occurrence_id,
            logical_run_id=logical_run_id,
            started_at="2020-01-01T00:00:00+00:00",
            stale_attempt_seconds=120,
        )
        self.assertEqual(receipt["status"], "running")
        result = self.run_occurrence(fetch=self.collector(), when=self.base_when, stale_attempt_seconds=0)
        attempts = result["receipt"]["attempts"]
        self.assertEqual(attempts[0]["outcome"], "interrupted")
        self.assertEqual(attempts[0]["failure_class"], "process_interrupted")
        self.assertEqual(result["receipt"]["status"], "completed")

    def test_secret_shaped_values_are_absent_from_evidence(self):
        result = self.run_occurrence(fetch=self.collector(quota=quota_payload()), when=self.base_when)
        evidence = Path(result["receipt"]["evidence_ref"]).read_text(encoding="utf-8")
        self.assertNotIn("must-not-be-persisted", evidence)
        self.assertNotIn("person@example.test", evidence)
        self.assertNotIn("not-written", evidence)

    def test_watcher_does_not_call_routing_or_cooldown_mutation(self):
        with patch.object(model_catalog, "dispatch_preflight", side_effect=AssertionError("routing must not run")), patch.object(model_catalog, "record_cooldown", side_effect=AssertionError("cooldown mutation must not run")):
            result = self.run_occurrence(fetch=self.collector(), when=self.base_when)
        self.assertEqual(result["receipt"]["status"], "completed")

    def test_run_due_reuses_existing_schedule_due_and_isolated_state(self):
        fetch = self.collector()
        with self.collector_env()[0], self.collector_env()[1]:
            first = watcher.run_due(self.schedule, state_home=self.state_home, when=self.base_when, fetch_json=fetch, sleep=lambda _seconds: None)
            second = watcher.run_due(self.schedule, state_home=self.state_home, when=self.base_when, fetch_json=fetch, sleep=lambda _seconds: None)
        self.assertTrue(first["attempted"])
        self.assertEqual(second["status"], "not_due")
        self.assertEqual(second["reason"], "already_submitted_for_due_window")
        self.assertTrue((self.state_home / watcher.STATE_DIR_NAME / "schedule-state.json").exists())
        self.assertFalse((Path.home() / ".local/share/runtime-agents/quota-watcher").exists() and self.state_home != Path.home() / ".local/share/runtime-agents")

    def test_bounded_loop_can_process_three_distinct_due_windows_without_daemon(self):
        times = iter([self.base_when, self.base_when, self.base_when + dt.timedelta(minutes=1), self.base_when + dt.timedelta(minutes=2)])
        with self.collector_env()[0], self.collector_env()[1]:
            payload = watcher.run_due_loop(
                state_home=self.state_home,
                schedule=self.schedule,
                occurrences=3,
                timeout_seconds=10,
                poll_interval=0,
                fetch_json=self.collector(),
                sleep=lambda _seconds: None,
                clock=lambda: next(times),
            )
        self.assertTrue(payload["complete"])
        self.assertEqual(payload["attempted_occurrences"], 3)
        self.assertEqual(len([row for row in payload["results"] if row.get("attempted")]), 3)

    def test_live_state_files_are_private_and_json_receipts_are_sanitized(self):
        result = self.run_occurrence(fetch=self.collector(), when=self.base_when)
        root = self.state_home / watcher.STATE_DIR_NAME
        self.assertEqual(self.state_home.stat().st_mode & 0o777, 0o700)
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(Path(result["receipt"]["evidence_ref"]).stat().st_mode & 0o777, 0o600)
        json.loads(Path(result["receipt"]["evidence_ref"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
