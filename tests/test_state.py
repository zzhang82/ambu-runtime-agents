import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime_agents import state


class StateHelpersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ra-state-"))

    def test_read_empty_jsonl(self):
        path = self.tmp / "events.jsonl"
        self.assertEqual(state.read_jsonl(path), [])

    def test_append_and_latest_by_id(self):
        path = self.tmp / "events.jsonl"
        state.append_jsonl(path, {"id": "a", "status": "queued"})
        state.append_jsonl(path, {"id": "a", "status": "running"})
        events = state.read_jsonl(path)
        latest = state.latest_by_id(events, "id")
        self.assertEqual(latest["a"]["status"], "running")

    def test_atomic_write_and_read_json(self):
        path = self.tmp / "x.json"
        state.atomic_write_json(path, {"ok": True})
        self.assertEqual(state.read_json(path, {}), {"ok": True})

    def test_ensure_private_file_no_crash(self):
        path = self.tmp / "f.txt"
        path.write_text("x", encoding="utf-8")
        state.ensure_private_file(path)


if __name__ == "__main__":
    unittest.main()
