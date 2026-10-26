import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from full.data_refresh_20261026 import export_bls_reader_v2_input as exporter


class BLSReaderV2ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.raw_dir = self.root / "raw"
        self.raw_dir.mkdir()
        raw_artifacts = []
        for index in range(256):
            path = self.raw_dir / (str(index) + ".json")
            path.write_text(json.dumps({"batch": index}), encoding="utf-8")
            raw_artifacts.append({"path": str(path), "sha256": self.hash_file(path)})
        self.observed = self.root / "observed.csv"
        self.observed.write_text("fixture\n", encoding="utf-8")
        self.missing = self.root / "missing.jsonl"
        with self.missing.open("w", encoding="utf-8") as stream:
            for index in range(12776):
                stream.write(json.dumps({"bls_period_code": "M10", "status": "source_missing"}) + "\n")
            for index in range(52):
                stream.write(json.dumps({"bls_period_code": "M13", "status": "period_not_returned"}) + "\n")
        self.results = self.root / "source-results.json"
        self.output = self.root / "legacy-results.json"
        self.source_result = {
            **exporter.EXPECTED_COUNTS,
            "status": exporter.SOURCE_STATUS,
            "note": "M13 is retained as annual. Missing periods remain missing.",
            "rawArtifacts": raw_artifacts,
            "otherCollectorField": {"must": "remain byte-value equivalent"},
        }
        self.source_document = {"result": self.source_result, "otherEnvelopeField": "unchanged"}
        self.write_source_document()
        self.patched_hashes = {
            "observed_csv": self.hash_file(self.observed),
            "missingness_jsonl": self.hash_file(self.missing),
            "collection_results": self.hash_file(self.results),
        }
        self.hash_patch = patch.object(exporter, "EXPECTED_HASHES", self.patched_hashes)
        self.hash_patch.start()

    def tearDown(self):
        self.hash_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def hash_file(path):
        return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

    def write_source_document(self):
        self.results.write_text(json.dumps(self.source_document, sort_keys=True) + "\n", encoding="utf-8")

    def export(self):
        repo_root = pathlib.Path(__file__).resolve().parents[3]
        return exporter.export(self.observed, self.missing, self.results, self.output, repo_root)

    def test_original_result_is_unchanged_and_legacy_view_changes_only_status(self):
        self.export()
        wrapper = json.loads(self.output.read_text(encoding="utf-8"))
        original_bytes = self.results.read_bytes()
        self.assertEqual(wrapper["normalizedFor"], "reader2.0.0_input_contract")
        self.assertEqual(wrapper["sourceCollectionStatus"], "collection_complete_with_source_gaps")
        self.assertEqual(wrapper["legacySnapshotCoverage"], "partial_due_to_documented_source_gaps")
        self.assertEqual(wrapper["originalResultSha256"], hashlib.sha256(original_bytes).hexdigest())
        self.assertEqual(wrapper["sourceCollectionDocument"], self.source_document)
        self.assertEqual(wrapper["sourceCollectionResult"], self.source_result)
        expected_legacy = dict(self.source_result, status="partial")
        self.assertEqual(wrapper["result"], expected_legacy)
        self.assertEqual(wrapper["result"]["rawArtifacts"], self.source_result["rawArtifacts"])
        self.assertEqual(wrapper["converter"]["moduleSha256"], exporter.sha256_file(pathlib.Path(exporter.__file__)))
        self.assertEqual(len(wrapper["converter"]["commit"]), 40)
        self.assertIsNone(wrapper["executedSourceSha256"])

    def test_incomplete_status_is_rejected(self):
        self.source_document["result"]["status"] = "partial"
        self.write_source_document()
        self.patched_hashes["collection_results"] = self.hash_file(self.results)
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            self.export()

    def test_wrong_count_is_rejected(self):
        self.source_document["result"]["observedRows"] -= 1
        self.write_source_document()
        self.patched_hashes["collection_results"] = self.hash_file(self.results)
        with self.assertRaisesRegex(ValueError, "count mismatch"):
            self.export()

    def test_changed_raw_response_is_rejected(self):
        raw = pathlib.Path(self.source_result["rawArtifacts"][0]["path"])
        raw.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "raw response is missing or changed"):
            self.export()


if __name__ == "__main__":
    unittest.main()
