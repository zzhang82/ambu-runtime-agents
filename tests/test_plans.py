import unittest

from runtime_agents import plans


class PlansTests(unittest.TestCase):
    def test_plan_draft(self):
        plan = {"plan_id": "p1", "status": "draft", "subtasks": [{"id": "1"}]}

        def q(*_args, **_kwargs):
            return None

        def e(*_args, **_kwargs):
            return None

        out = plans.derive_plan_status(plan, q, e)
        self.assertEqual(out["status"], "draft")

    def test_failed_subtask_blocks_plan(self):
        plan = {"plan_id": "p1", "status": "approved", "subtasks": [{"id": "1"}, {"id": "2"}]}

        def q(plan_id, sid):
            if sid == "1":
                return {"queue_id": "q1", "status": "completed", "task_id": "t1"}
            return {"queue_id": "q2", "status": "failed", "task_id": "t2"}

        def e(*_args, **_kwargs):
            return None

        out = plans.derive_plan_status(plan, q, e)
        self.assertEqual(out["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
