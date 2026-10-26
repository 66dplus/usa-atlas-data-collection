import json
import tempfile
import unittest
from pathlib import Path

from database.reader.v2.load_local_review import sha256
from database.reader.v2 import load_refresh_local_review
from database.reader.v2.load_refresh_local_review import checked_manifest


class RefreshLoaderManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="reader-refresh-test-", dir="/tmp/usa-maps-data-flow-20261026")
        self.root = Path(self.tmp.name)
        self.raw = self.root / "official-source.csv"
        self.raw.write_text("id,value\n1,2\n", encoding="utf-8")
        self.prepared = self.root / "prepared.csv"
        self.prepared.write_text("id,value\n1,2\n", encoding="utf-8")
        self.output = self.root / "normalized.jsonl"
        self.output.write_text('{"candidate_status":"local_review"}\n', encoding="utf-8")
        self.manifest_path = self.root / "refresh-manifest.json"
        self.manifest = {
            "candidate_status":"local_review_not_admitted",
            "contract_version":"2.0.0",
            "collector_version":"data-refresh-preparation-2026.10.26.1",
            "inputs":{"prepared":{"path":str(self.prepared),"sha256":sha256(self.prepared)}},
            "verified_raw_sources":{"source":{"path":str(self.raw),"sha256":sha256(self.raw)}},
            "output":{"path":str(self.output),"sha256":sha256(self.output),"rows":1},
        }
        self.write_manifest()

    def tearDown(self):
        self.tmp.cleanup()

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_manifest_requires_local_candidate_and_all_source_hashes(self):
        _, _, output = checked_manifest(self.manifest_path)
        self.assertEqual(output, self.output.resolve())
        self.raw.write_text("id,value\n1,changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source artifact.*corrupt"):
            checked_manifest(self.manifest_path)

    def test_manifest_refuses_corrupt_prepared_and_normalized_inputs(self):
        self.prepared.write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "prepared refresh input.*corrupt"):
            checked_manifest(self.manifest_path)
        self.prepared.write_text("id,value\n1,2\n", encoding="utf-8")
        self.output.write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "normalized refresh JSONL.*corrupt"):
            checked_manifest(self.manifest_path)

    def test_loader_independently_checks_native_national_pep_and_rates(self):
        pep = self.root / "native-pep.csv"
        lines = ["SEX,AGE,POPESTIMATE2023,POPESTIMATE2024", "0,999,1000,1100"]
        lines.extend(f"0,{age},{age + 1},{age + 2}" for age in range(18))
        pep.write_text("\n".join(lines) + "\n", encoding="utf-8")
        digest = sha256(pep)
        previous = load_refresh_local_review.NATIVE_PEP_SHA256
        load_refresh_local_review.NATIVE_PEP_SHA256 = digest
        try:
            rows = []
            estimates = {
                (2023,"01.01:pep_population_total"):1000,
                (2023,"01.01:pep_population_age_13_plus"):909,
                (2023,"01.01:pep_population_under_18"):171,
                (2024,"01.01:pep_population_total"):1100,
                (2024,"01.01:pep_population_age_13_plus"):996,
                (2024,"01.01:pep_population_under_18"):189,
            }
            for (year,field), value in estimates.items():
                rows.append({"dataset_id":"pep_population","field_id":field,"geo_type":"nation","geo_id":"US",
                    "period_year":year,"value":str(value),"quality_status":"observed","source_sha256":digest})
            rows.extend([
                {"dataset_id":"irs_agi","field_id":"07.01:derived:per-resident","geo_type":"nation","geo_id":"US","period_year":2023,"quality_status":"observed","raw_estimate":"1","raw_denominator":"1000","value":"1"},
                {"dataset_id":"cancer","field_id":"11.01","geo_type":"nation","geo_id":"US","period_year":2023,"quality_status":"observed","raw_estimate":"1941540","raw_denominator":"1000","value":"194154000"},
            ])
            output = self.root / "native-observations.jsonl"
            output.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            manifest = {"verified_raw_sources":{"pep_nation_age":{"sourceId":load_refresh_local_review.NATIVE_PEP_SOURCE_ID,"path":str(pep),"sha256":digest}}}
            load_refresh_local_review.verify_native_pep_source(manifest, output)
            rows[0]["value"] = "999"
            output.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs from independently verified"):
                load_refresh_local_review.verify_native_pep_source(manifest, output)
        finally:
            load_refresh_local_review.NATIVE_PEP_SHA256 = previous

    def test_catalog_release_keys_follow_each_actual_source_release(self):
        self.output.write_text("".join(json.dumps({"catalog_field_id":"11.01","source_release":release})+"\n"
            for release in ("2025 NPCR/SEER submission released June 2026; diagnosis year 2023","USCS 2026 submission; 2023 incidence")),encoding="utf-8")
        mapped=load_refresh_local_review.source_releases_by_field(self.output)
        self.assertEqual(mapped["11.01"],{"2025 NPCR/SEER submission released June 2026; diagnosis year 2023","USCS 2026 submission; 2023 incidence"})


if __name__ == "__main__":
    unittest.main()
