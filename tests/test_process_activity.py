import sys
import time
import unittest
from pathlib import Path

from runtime_agents import cli


class ProcessActivityTests(unittest.TestCase):
    def setUp(self):
        self.cwd = Path(__file__).resolve().parents[1]

    def test_silent_process_times_out_on_inactivity(self):
        started = time.monotonic()
        result = cli.run_command(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            self.cwd,
            timeout=0,
            inactivity_timeout=0.3,
            max_timeout=30,
        )
        elapsed = time.monotonic() - started

        self.assertEqual(result["returncode"], 124)
        self.assertIn("pipe inactivity", result["stderr"])
        self.assertLess(elapsed, 2.0)
        self.assertIn("started_at", result)
        self.assertIn("ended_at", result)

    def test_streaming_process_resets_inactivity_timer(self):
        code = (
            "import time, sys\n"
            "[sys.stdout.write(f'{i}\\n') or sys.stdout.flush() or time.sleep(0.1) for i in range(5)]\n"
        )
        result = cli.run_command(
            [sys.executable, "-c", code],
            self.cwd,
            timeout=0,
            inactivity_timeout=0.3,
            max_timeout=30,
        )

        self.assertEqual(result["returncode"], 0)
        self.assertIn("0\n", result["stdout"])
        self.assertIn("4\n", result["stdout"])

    def test_immediate_process_succeeds(self):
        result = cli.run_command(
            [sys.executable, "-c", "print('ok')"],
            self.cwd,
            timeout=0,
            inactivity_timeout=0.3,
            max_timeout=30,
        )

        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"].strip(), "ok")


if __name__ == "__main__":
    unittest.main()
