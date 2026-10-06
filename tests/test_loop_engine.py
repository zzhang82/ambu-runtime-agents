import unittest

from runtime_agents import loop_engine


class LoopEngineTests(unittest.TestCase):
    def test_normalize_strips_ansi_and_timestamps_and_timings(self):
        raw = "\x1b[31mFAIL: test_something (0.045 seconds)\x1b[0m\n2026-10-05T14:23:01Z [ERROR] failed in 1.23s\n"
        norm = loop_engine.normalize_check_output(raw)
        self.assertNotIn("\x1b[31m", norm)
        self.assertNotIn("0.045 seconds", norm)
        self.assertNotIn("2026-10-05T14:23:01Z", norm)
        self.assertNotIn("1.23s", norm)
        self.assertIn("FAIL: test_something", norm)

    def test_normalize_strips_pytest_timing_banner(self):
        banner1 = "================ 1 failed, 2 passed in 0.42s ================"
        banner2 = "================ 1 failed, 2 passed in 1.89s ================"
        norm1 = loop_engine.normalize_check_output(banner1)
        norm2 = loop_engine.normalize_check_output(banner2)
        self.assertEqual(norm1, norm2)
        self.assertEqual(norm1, "================ 1 failed, 2 passed ================")

    def test_normalize_strips_memory_addresses_and_pids_and_tempdirs(self):
        raw = "Object at 0x7f4a3b2c1d00 failed in process pid=98712\nWriting dump to /tmp/pytest-run-98712/artifact.log\n"
        norm = loop_engine.normalize_check_output(raw)
        self.assertNotIn("0x7f4a3b2c1d00", norm)
        self.assertNotIn("98712", norm)
        self.assertNotIn("pytest-run-98712", norm)
        self.assertIn("<MEM_ADDR>", norm)
        self.assertIn("pid=<PID>", norm)
        self.assertIn("/tmp/<TEMPDIR>", norm)

    def test_normalize_preserves_source_line_numbers(self):
        raw = '  File "src/app.py", line 42, in process_user\n    raise ValueError("invalid")\n'
        norm = loop_engine.normalize_check_output(raw)
        self.assertIn('line 42', norm)

    def test_fingerprint_identical_across_timing_and_mem_variations(self):
        out1 = "FAILED tests/test_auth.py::test_login - in 0.12s\nat 0x7f1234567890\n"
        out2 = "FAILED tests/test_auth.py::test_login - in 0.99s\nat 0x7fabcdef0123\n"
        fp1 = loop_engine.fingerprint_check_failure(out1, "", 1)
        fp2 = loop_engine.fingerprint_check_failure(out2, "", 1)
        self.assertEqual(fp1, fp2)

    def test_fingerprint_differs_on_partial_progress(self):
        # Round 1: 2 tests failed
        out_round1 = "FAILED tests/test_a.py::test_one\nFAILED tests/test_b.py::test_two\n=== 2 failed ==="
        # Round 2: Agent fixed test_one, only test_two still fails
        out_round2 = "FAILED tests/test_b.py::test_two\n=== 1 failed, 1 passed ==="
        fp1 = loop_engine.fingerprint_check_failure(out_round1, "", 1)
        fp2 = loop_engine.fingerprint_check_failure(out_round2, "", 1)
        self.assertNotEqual(fp1, fp2, "Partial progress must yield different fingerprint to avoid false halt")

    def test_fingerprint_differs_when_line_number_shifts(self):
        # Code was edited, shifting the failure to another line
        out_line42 = '  File "src/auth.py", line 42, in login\n    assert token is not None\n'
        out_line55 = '  File "src/auth.py", line 55, in login\n    assert token is not None\n'
        fp1 = loop_engine.fingerprint_check_failure(out_line42, "", 1)
        fp2 = loop_engine.fingerprint_check_failure(out_line55, "", 1)
        self.assertNotEqual(fp1, fp2, "Line number shift reflects code modification and must change fingerprint")

    def test_gap_classification_check_rubric_127_and_126(self):
        kind127, detail127 = loop_engine.classify_gap("", "", 127)
        self.assertEqual(kind127, "check_rubric")
        self.assertIn("127", detail127)

        kind126, detail126 = loop_engine.classify_gap("", "", 126)
        self.assertEqual(kind126, "check_rubric")
        self.assertIn("126", detail126)

    def test_gap_classification_environment_shell_stderr(self):
        stderr = "bash: cargo: command not found\n"
        kind, detail = loop_engine.classify_gap("", stderr, 1)
        self.assertEqual(kind, "environment")
        self.assertIn("Missing system binary", detail)

    def test_gap_classification_transient_error(self):
        stderr = "Error: 429 Too Many Requests rate limit exceeded\n"
        kind, detail = loop_engine.classify_gap("", stderr, 1)
        self.assertEqual(kind, "transient")

    def test_gap_classification_klaus_trap_stdout_app_strings_remain_execution(self):
        # Even if stdout contains "user not found" or "no such file", it must NOT be classified as environment
        stdout = "AssertionError: Expected 'user not found' but got None\nFileNotFoundError: test_data.json\n"
        kind, detail = loop_engine.classify_gap(stdout, "", 1)
        self.assertEqual(kind, "execution", "Application logic asserting 'not found' must NOT trigger environment gap")

    def test_gap_classification_clean_pass(self):
        kind, detail = loop_engine.classify_gap("OK", "", 0)
        self.assertEqual(kind, "none")

    def test_should_halt_anti_loop_threshold(self):
        counts = {}
        halt, counts, count = loop_engine.should_halt("fp-alpha", counts, max_same_failure=2)
        self.assertFalse(halt)
        self.assertEqual(count, 1)

        # Second failure with same fingerprint triggers halt
        halt, counts, count = loop_engine.should_halt("fp-alpha", counts, max_same_failure=2)
        self.assertTrue(halt)
        self.assertEqual(count, 2)

    def test_should_halt_with_interleaved_fingerprints(self):
        counts = {}
        # Round 1: fp1
        halt, counts, _ = loop_engine.should_halt("fp1", counts, max_same_failure=2)
        self.assertFalse(halt)
        # Round 2: fp2 (different failure)
        halt, counts, _ = loop_engine.should_halt("fp2", counts, max_same_failure=2)
        self.assertFalse(halt)
        # Round 3: fp1 again
        halt, counts, _ = loop_engine.should_halt("fp1", counts, max_same_failure=2)
        self.assertTrue(halt, "Cumulative identical failure must trigger halt")

    def test_check_eval_artifacts_validation(self):
        import tempfile
        import shutil
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        try:
            # Empty list passes
            ok, err = loop_engine.check_eval_artifacts(tmp, [])
            self.assertTrue(ok)
            self.assertEqual(err, "")

            # Non-existent file fails
            ok, err = loop_engine.check_eval_artifacts(tmp, ["dist/bundle.js"])
            self.assertFalse(ok)
            self.assertIn("does not exist", err)

            # Empty file fails
            (tmp / "empty.txt").write_text("", encoding="utf-8")
            ok, err = loop_engine.check_eval_artifacts(tmp, ["empty.txt"])
            self.assertFalse(ok)
            self.assertIn("empty (0 bytes)", err)

            # Valid non-empty file passes
            (tmp / "valid.json").write_text('{"status": "ok"}\n', encoding="utf-8")
            ok, err = loop_engine.check_eval_artifacts(tmp, ["valid.json"])
            self.assertTrue(ok)
            self.assertEqual(err, "")

            # Path traversal escaping workspace fails
            ok, err = loop_engine.check_eval_artifacts(tmp, ["../outside.txt"])
            self.assertFalse(ok)
            self.assertIn("escapes workspace", err)
        finally:
            shutil.rmtree(tmp)

    def test_build_iteration_prompt_tailors_to_gap_kind(self):
        # Environment gap
        p_env = loop_engine.build_iteration_prompt(
            "setup project", "cargo build", ["dist/app"], "", "bash: cargo: not found",
            "environment", "Missing system binary", "workspace_write"
        )
        self.assertIn("[environment]", p_env)
        self.assertIn("missing dependency or system binary", p_env)
        self.assertIn("dist/app", p_env)

        # Check rubric gap
        p_rubric = loop_engine.build_iteration_prompt(
            "run check", "invalid_cmd", None, "", "",
            "check_rubric", "Exit 127", "workspace_write"
        )
        self.assertIn("[check_rubric]", p_rubric)
        self.assertIn("check command itself failed to execute", p_rubric)

        # Read-only autonomy
        p_ro = loop_engine.build_iteration_prompt(
            "analyze problem", "pytest", None, "", "AssertionError",
            "execution", "Test failed", "read_only"
        )
        self.assertIn("Do not edit files", p_ro)


if __name__ == "__main__":
    unittest.main()
