import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import collect


class ContractTests(unittest.TestCase):
    def test_contract_covers_all_81_catalog_rows(self):
        result = collect.validate_contract()
        self.assertEqual(result["status"], "pass", result["errors"])
        self.assertEqual(result["rows"], 81)
        self.assertEqual(result["state_totals"], {
            "run_now": 46,
            "blocked_access": 19,
            "definition_required": 7,
            "source_required": 6,
            "license_required": 3,
        })

    def test_all_run_now_rows_are_executable_and_rate_limited(self):
        contract = collect.load_json(collect.CONTRACT_PATH)
        config = collect.load_json(collect.CONFIG_PATH)["profiles"]
        active = [row for row in contract if row["planned_state"] == "run_now"]
        self.assertEqual(len(active), 46)
        for row in active:
            self.assertTrue(row["source_selector"], row["field_id"])
            self.assertTrue(row["source_variables"], row["field_id"])
            self.assertTrue(row["target_geographies"], row["field_id"])
            self.assertIn(row["rate_limit_profile"], config)
            self.assertFalse(any(value.startswith("group:") for value in row["source_variables"]), row["field_id"])
            if row["rate_limit_profile"] == "census_acs":
                self.assertTrue(all(collect.re.fullmatch(r"[A-Z]\d+_\d{3}[EM]", value)
                                    for value in row["source_variables"]), row["field_id"])

    def test_variable_ranges_are_expanded_deterministically(self):
        self.assertEqual(
            collect._expand_range("B15003_017E:B15003_019E"),
            ["B15003_017E", "B15003_018E", "B15003_019E"],
        )

    def test_bls_contract_uses_exact_state_and_county_templates(self):
        contract = collect.load_json(collect.CONTRACT_PATH)
        row = next(item for item in contract if item["field_id"] == "03.06")
        self.assertEqual(row["source_variables"], collect.BLS_LAUS_VARIABLE_TEMPLATES)
        self.assertEqual(len(row["source_variables"]), 8)
        self.assertFalse(any("..." in value for value in row["source_variables"]))

    def test_bls_placeholder_prose_is_rejected(self):
        contract = collect.load_json(collect.CONTRACT_PATH)
        row = next(item for item in contract if item["field_id"] == "03.06")
        row["source_variables"] = ["LAUST...03", "supporting measures 04/05/06"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with mock.patch.object(collect, "CONTRACT_PATH", path):
                result = collect.validate_contract()
        self.assertEqual(result["status"], "fail")
        self.assertIn("BLS variables must be exact state/county LAUS templates 03-06", result["errors"][0])

    def test_normalized_key_components_are_explicit(self):
        record = collect.normalized(
            "01.01", "06001", "county", "2024", 1, "count", "test", "release", "https://example.test/data"
        )
        key = tuple(record[name] for name in ("geo_id", "year", "field_id", "source_release"))
        self.assertEqual(key, ("06001", "2024", "01.01", "release"))

    def test_completed_source_skips_transport_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            here = Path(directory)
            path = here / "normalized" / "census_acs.jsonl.gz"
            path.parent.mkdir()
            path.write_bytes(b"stable")
            manifest = {"sources": {"census_acs": {
                "status": "pass",
                "normalized_artifact": {
                    "path": "normalized/census_acs.jsonl.gz",
                    "sha256": collect.sha256(b"stable"),
                    "duplicate_keys": 0,
                },
            }}}
            transport = mock.Mock()
            with mock.patch.object(collect, "HERE", here):
                if not collect.source_is_complete(manifest, "census_acs"):
                    transport()
            transport.assert_not_called()

    def test_completed_raw_job_uses_cache_without_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)
            path = raw / "full" / "fbi_cde" / "job.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"ok":true}\n')
            session = mock.Mock(cache_hits=0)
            with mock.patch.object(collect, "RAW", raw), mock.patch.object(collect, "HERE", raw):
                expected_hash = collect.record_artifact_hash(path)
                payload, artifact = collect.request_cached(
                    session, "fbi_cde", "job.json", "https://example.test/job"
                )
        self.assertEqual(payload, b'{"ok":true}\n')
        self.assertTrue(artifact["cache_hit"])
        self.assertEqual(artifact["sha256"], expected_hash)
        self.assertEqual(session.cache_hits, 1)
        session.request.assert_not_called()

    def test_corrupted_cached_job_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)
            path = raw / "full" / "fbi_cde" / "job.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"ok":true}\n')
            session = mock.Mock(cache_hits=0)
            with mock.patch.object(collect, "RAW", raw), mock.patch.object(collect, "HERE", raw):
                collect.record_artifact_hash(path)
                path.write_bytes(b'{"ok":false}\n')
                with self.assertRaisesRegex(collect.StopSource, "cache_hash_mismatch"):
                    collect.request_cached(session, "fbi_cde", "job.json", "https://example.test/job")
        session.request.assert_not_called()

    def test_existing_unbound_cached_job_fails_without_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)
            path = raw / "full" / "fbi_cde" / "job.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"ok":true}\n')
            session = mock.Mock(cache_hits=0)
            with mock.patch.object(collect, "RAW", raw), mock.patch.object(collect, "HERE", raw):
                with self.assertRaisesRegex(collect.StopSource, "cache_hash_record_missing"):
                    collect.request_cached(session, "fbi_cde", "job.json", "https://example.test/job")
        session.request.assert_not_called()

    def test_cached_job_with_stale_binding_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)
            path = raw / "full" / "fbi_cde" / "job.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"ok":true}\n')
            session = mock.Mock(cache_hits=0)
            with mock.patch.object(collect, "RAW", raw), mock.patch.object(collect, "HERE", raw):
                collect.record_artifact_hash(path)
                binding = collect.load_json(collect.binding_sidecar(path))
                binding["plan_sha256"] = "0" * 64
                collect.write_json(collect.binding_sidecar(path), binding)
                with self.assertRaisesRegex(collect.StopSource, "cache_binding_mismatch"):
                    collect.request_cached(session, "fbi_cde", "job.json", "https://example.test/job")
        session.request.assert_not_called()

    def test_eia_enforces_configured_page_cap(self):
        response = {"response": {"total": "2", "data": [{
            "period": "2024", "price": "1.0", "price-units": "unit",
            "stateid": "CA", "sectorid": "RES",
        }]}}
        session = mock.Mock(config={"max_pages": 1})
        artifact = {"path": "raw/full/eia/page.json", "sha256": "0" * 64, "bytes": 1}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(collect.os.environ, {"EIA_API_KEY": "test"}), \
                mock.patch.object(collect, "NORMALIZED", Path(directory)), \
                mock.patch.object(collect, "request_cached", return_value=(json.dumps(response).encode(), artifact)) as request:
            with self.assertRaisesRegex(collect.StopSource, "max_pages"):
                collect.full_eia(session)
        request.assert_called_once()

    def test_duplicate_normalized_keys_are_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            normalized = Path(directory) / "normalized"
            path = normalized / "fbi_cde.jsonl"
            record = collect.normalized(
                "04.01", "CA", "state", "2024", 1, "count", "fbi_cde", "release",
                "https://example.test/data",
            )
            normalized.mkdir()
            path.write_text(json.dumps(record) + "\n" + json.dumps(record) + "\n", encoding="utf-8")
            with mock.patch.object(collect, "NORMALIZED", normalized), mock.patch.object(collect, "HERE", Path(directory)):
                result = collect.inspect_normalized_output("fbi_cde")
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["duplicate_keys"], 1)

    def test_interrupted_rebuild_matches_uninterrupted_normalized_hash(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(collect, "NORMALIZATION_TIMESTAMP", "2026-09-19T00:00:00+00:00"):
            root = Path(directory)
            uninterrupted = root / "uninterrupted.jsonl.gz"
            resumed = root / "resumed.jsonl.gz"
            job_one = [collect.normalized(
                "01.01", "06", "state", "2024", 1, "count", "census_acs", "release",
                "https://example.test/data",
            )]
            job_two = [collect.normalized(
                "01.01", "12", "state", "2024", 2, "count", "census_acs", "release",
                "https://example.test/data",
            )]
            collect.append_jsonl(uninterrupted, job_one)
            collect.append_jsonl(uninterrupted, job_two)
            collect.append_jsonl(resumed, job_one)
            resumed.unlink()
            collect.append_jsonl(resumed, job_one)
            collect.append_jsonl(resumed, job_two)
            uninterrupted_hash = collect.sha256(uninterrupted.read_bytes())
            resumed_hash = collect.sha256(resumed.read_bytes())
        self.assertEqual(resumed_hash, uninterrupted_hash)

    def test_run_full_resume_reuses_completed_job_and_matches_uninterrupted_hash(self):
        fixed_time = "2026-09-19T00:00:00+00:00"

        class FixtureSession:
            transports: dict[str, int] = {}

            def __init__(self, profile, *, calibration):
                self.profile = profile
                self.calibration = calibration
                self.config = {"max_response_bytes": 1024, "max_attempts": 1,
                               "retryable_statuses": [], "max_pages": 1}
                self.requests = self.response_bytes = self.retries = self.http_429 = self.cache_hits = 0

            def request(self, url, **_kwargs):
                self.requests += 1
                self.transports[url] = self.transports.get(url, 0) + 1
                payload = json.dumps({"value": int(url.rsplit("-", 1)[-1])}).encode()
                self.response_bytes += len(payload)
                return payload

            def metrics(self):
                return {"request_count": self.requests, "response_bytes": self.response_bytes,
                        "retry_count": self.retries, "http_429_count": self.http_429,
                        "cache_hit_count": self.cache_hits, "duration_seconds": 0.0}

        def scenario(root: Path, *, interrupt_once: bool) -> tuple[str, dict[str, int]]:
            raw, normalized, state = root / "raw", root / "normalized", root / "state"
            calibration = state / "calibration-report.json"
            manifest = state / "run-manifest.json"
            status = state / "status.json"
            eval_path = root / "FIELD-EVAL.json"
            state.mkdir(parents=True)
            collect.write_json(calibration, {**collect.current_bindings(), "sources": {
                "fbi_cde": {"status": "pass", "artifacts": []},
            }})
            interrupted = False

            def runner(session):
                nonlocal interrupted
                artifacts = []
                for number in (1, 2):
                    url = f"https://example.test/job-{number}"
                    payload, artifact = collect.request_cached(
                        session, "fbi_cde", f"job-{number}.json", url,
                    )
                    artifacts.append(artifact)
                    value = json.loads(payload)["value"]
                    collect.append_jsonl(collect.source_output("fbi_cde"), [collect.normalized(
                        f"04.01:fixture_{number}", "CA", "state", "2024", value, "count",
                        "fbi_cde", "fixture-release", url, catalog_field_id="04.01",
                    )])
                    if interrupt_once and not interrupted and number == 1:
                        interrupted = True
                        raise KeyboardInterrupt
                return 2, artifacts

            FixtureSession.transports = {}
            with mock.patch.object(collect, "HERE", root), \
                    mock.patch.object(collect, "RAW", raw), \
                    mock.patch.object(collect, "NORMALIZED", normalized), \
                    mock.patch.object(collect, "STATE", state), \
                    mock.patch.object(collect, "CALIBRATION_PATH", calibration), \
                    mock.patch.object(collect, "MANIFEST_PATH", manifest), \
                    mock.patch.object(collect, "STATUS_PATH", status), \
                    mock.patch.object(collect, "EVAL_PATH", eval_path), \
                    mock.patch.object(collect, "FULL_RUNNERS", {"fbi_cde": runner}), \
                    mock.patch.object(collect, "Session", FixtureSession), \
                    mock.patch.object(collect.safety, "load_credentials"), \
                    mock.patch.object(collect, "build_eval", return_value={}), \
                    mock.patch.object(collect, "now", return_value=fixed_time):
                if interrupt_once:
                    with self.assertRaises(KeyboardInterrupt):
                        collect.run_full()
                    collect.mark_interrupted()
                    requests_before_resume = dict(FixtureSession.transports)
                    self.assertEqual(collect.run_full(), 0)
                    self.assertEqual(FixtureSession.transports["https://example.test/job-1"],
                                     requests_before_resume["https://example.test/job-1"])
                else:
                    self.assertEqual(collect.run_full(), 0)
                output_hash = collect.sha256(collect.source_output("fbi_cde").read_bytes())
                final_manifest = collect.load_json(manifest)
                self.assertEqual(final_manifest["status"], "complete")
            return output_hash, dict(FixtureSession.transports)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            resumed_hash, resumed_transport = scenario(base / "resumed", interrupt_once=True)
            uninterrupted_hash, uninterrupted_transport = scenario(base / "uninterrupted", interrupt_once=False)
        self.assertEqual(resumed_hash, uninterrupted_hash)
        self.assertEqual(resumed_transport, uninterrupted_transport)


class ArtifactTests(unittest.TestCase):
    def test_every_declared_calibration_artifact_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            here = Path(directory)
            path = here / "raw" / "calibration" / "source" / "payload.json"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"ok":true}\n')
            with mock.patch.object(collect, "HERE", here):
                digest = collect.record_artifact_hash(path)
                report = {"sources": {"source": {"artifacts": [{
                    "path": "raw/calibration/source/payload.json", "sha256": digest,
                }]}}}
                self.assertEqual(collect.validate_calibration_artifacts(report), 1)
                path.write_bytes(b'{"ok":false}\n')
                with self.assertRaisesRegex(collect.StopSource, "cache_hash_mismatch"):
                    collect.validate_calibration_artifacts(report)

    def test_calibration_with_stale_binding_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            collect.write_json(path, {"sources": {}})
            with mock.patch.object(collect, "CALIBRATION_PATH", path):
                with self.assertRaisesRegex(collect.StopSource, "calibration_binding_mismatch"):
                    collect.refresh_calibration_evidence()

    def test_interruption_updates_manifest_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            status_path = Path(directory) / "status.json"
            collect.write_json(manifest_path, {"status": "running", "pid": collect.os.getpid(), "sources": {}})
            with mock.patch.object(collect, "MANIFEST_PATH", manifest_path), \
                    mock.patch.object(collect, "STATUS_PATH", status_path):
                collect.mark_interrupted()
            manifest = collect.load_json(manifest_path)
            status = collect.load_json(status_path)
        self.assertEqual(manifest["status"], "interrupted")
        self.assertEqual(status["status"], "interrupted")

    def test_eval_always_covers_81_rows_and_blocked_is_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            eval_path = Path(directory) / "eval.json"
            with mock.patch.object(collect, "EVAL_PATH", eval_path), \
                    mock.patch.object(collect, "CALIBRATION_PATH", Path(directory) / "missing-cal.json"), \
                    mock.patch.object(collect, "MANIFEST_PATH", Path(directory) / "missing-run.json"):
                report = collect.build_eval()
        self.assertEqual(report["total"], 81)
        self.assertEqual(sum(report["totals"].values()), 81)
        blocked = [row for row in report["fields"] if row["expected"].startswith("planned_state=blocked_access")]
        self.assertTrue(blocked)
        self.assertTrue(all(row["result"] == "BLOCKED" for row in blocked))
        self.assertTrue(all(len(row["evidence_sha256"]) == 64 for row in report["fields"]))

    def test_saved_json_removes_credentials_and_email(self):
        payload = {
            "api_key": "secret",
            "url": "https://example.test/data?key=secret&email=person%40example.com&state=06",
        }
        cleaned = collect.safety.sanitize_data(payload)
        serialized = json.dumps(cleaned)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("person", serialized)
        self.assertIn("state=06", serialized)


if __name__ == "__main__":
    unittest.main()
