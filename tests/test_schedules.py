import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import schedules


class SchedulesTests(unittest.TestCase):
    def test_cron_wildcard(self):
        now = dt.datetime(2026, 1, 1, 10, 5).astimezone()
        self.assertTrue(schedules.cron_matches_now("* * * * *", now))

    def test_cron_exact(self):
        now = dt.datetime(2026, 1, 1, 10, 5).astimezone()
        self.assertTrue(schedules.cron_matches_now("5 10 1 1 *", now))

    def test_cron_list_range_step(self):
        now = dt.datetime(2026, 1, 1, 10, 6).astimezone()
        self.assertTrue(schedules.cron_matches_now("*/3 9-11 1,2 1 *", now))

    def test_schedule_due_idempotent(self):
        now = dt.datetime(2026, 1, 1, 10, 5).astimezone()
        due, window = schedules.schedule_due({"enabled": True, "cron": "* * * * *"}, now)
        self.assertTrue(due)
        due2, reason2 = schedules.schedule_due({"enabled": True, "cron": "* * * * *", "last_due_window": window}, now)
        self.assertFalse(due2)
        self.assertEqual(reason2, "already_submitted_for_due_window")


if __name__ == "__main__":
    unittest.main()
