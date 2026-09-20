import errno
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import collect
import server_runner


class ServerRunnerTests(unittest.TestCase):
    def test_select_source_keeps_only_requested_runner(self):
        census = object()
        result = server_runner.select_source({"census_acs": census, "eia": object()}, "census_acs")
        self.assertEqual(result, {"census_acs": census})

    def test_unknown_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown source"):
            server_runner.select_source({"census_acs": object()}, "missing")

    def test_calibrate_if_needed_reuses_verified_report(self):
        with mock.patch.object(server_runner, "calibration_ready", return_value=True), \
                mock.patch.object(collect, "run_calibration") as run:
            self.assertEqual(server_runner.calibrate_if_needed("census_acs"), 0)
        run.assert_not_called()

    def test_calibrate_if_needed_limits_dispatch(self):
        census = object()
        with mock.patch.object(server_runner, "calibration_ready", return_value=False), \
                mock.patch.object(collect, "CALIBRATORS", {"census_acs": census, "eia": object()}), \
                mock.patch.object(collect, "run_calibration", return_value=0) as run:
            self.assertEqual(server_runner.calibrate_if_needed("census_acs"), 0)
            self.assertEqual(collect.CALIBRATORS, {"census_acs": census})
        run.assert_called_once_with()

    def test_run_source_limits_dispatch(self):
        census = object()
        with mock.patch.object(collect, "FULL_RUNNERS", {"census_acs": census, "eia": object()}), \
                mock.patch.object(collect, "run_full", return_value=0) as run:
            self.assertEqual(server_runner.run_source("census_acs"), 0)
            self.assertEqual(collect.FULL_RUNNERS, {"census_acs": census})
        run.assert_called_once_with()

    def test_status_selects_requested_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "run-manifest.json"
            status_path = root / "status.json"
            manifest_path.write_text(json.dumps({
                "status": "partial",
                "sources": {
                    "census_acs": {"status": "fail", "reason": "timeout"},
                    "eia": {"status": "pass", "normalized_rows": 1},
                },
            }), encoding="utf-8")
            status_path.write_text(json.dumps({
                "status": "running", "source": "eia", "pid": 123,
            }), encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(collect, "MANIFEST_PATH", manifest_path), \
                    mock.patch.object(collect, "STATUS_PATH", status_path), \
                    mock.patch.object(server_runner.os, "kill"), \
                    mock.patch.object(sys, "stdout", output):
                self.assertEqual(server_runner.source_status("census_acs"), 0)
            result = json.loads(output.getvalue())
        self.assertEqual(result["source"], "census_acs")
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["details"]["reason"], "timeout")
        self.assertEqual(result["runtime"], {"status": "not_running_for_source", "active_source": "eia"})

    def test_status_requires_source(self):
        with mock.patch.object(sys, "argv", ["server_runner.py", "status"]), \
                mock.patch.object(sys, "stderr", io.StringIO()):
            with self.assertRaisesRegex(SystemExit, "2"):
                server_runner.main()

    def test_calibration_ready_verifies_selected_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "calibration-report.json"
            payload = root / "raw" / "cal.json"
            payload.parent.mkdir()
            payload.write_text("{}", encoding="utf-8")
            bindings = {"plan_sha256": "p", "contract_sha256": "c",
                        "config_sha256": "g", "collector_sha256": "s"}
            report_path.write_text(json.dumps({**bindings, "sources": {"census_acs": {
                "status": "pass", "artifacts": [{"path": "raw/cal.json", "sha256": "digest"}],
            }}}), encoding="utf-8")
            with mock.patch.object(collect, "CALIBRATION_PATH", report_path), \
                    mock.patch.object(collect, "HERE", root), \
                    mock.patch.object(collect, "current_bindings", return_value=bindings), \
                    mock.patch.object(collect, "verified_file_artifact", return_value={"sha256": "digest"}):
                self.assertTrue(server_runner.calibration_ready("census_acs"))

    def test_lock_contention_fails_without_waiting(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(server_runner.fcntl, "flock", side_effect=OSError(errno.EAGAIN, "busy")):
            with self.assertRaisesRegex(server_runner.RunnerBusy, "another collector"):
                with server_runner.exclusive_lock(Path(directory) / "runner.lock"):
                    self.fail("lock body must not execute")


if __name__ == "__main__":
    unittest.main()
