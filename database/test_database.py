from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import load


ROOT = Path(__file__).resolve().parent.parent / "full"


def scalar(sql: str) -> str:
    return load.psql(["--tuples-only", "--no-align", "--command", sql], capture=True)


def maintenance_scalar(sql: str) -> str:
    return load.psql(["--tuples-only", "--no-align", "--command", sql],
                     dbname=load.MAINTENANCE_DATABASE, capture=True)


@contextmanager
def postgres_cluster():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        data = root / "data"
        socket_dir = root / "socket"
        socket_dir.mkdir()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        subprocess.run(["initdb", "-D", str(data), "-A", "trust", "-U", "postgres",
                        "--no-locale"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        subprocess.run(["pg_ctl", "-D", str(data), "-o", f"-F -k {socket_dir} -p {port}",
                        "-w", "start"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        environment = {
            "PGHOST": str(socket_dir), "PGPORT": str(port),
            "PGUSER": "postgres", "PGDATABASE": "postgres",
        }
        try:
            with mock.patch.dict(os.environ, environment):
                load.psql(["--command", "CREATE ROLE usa_atlas_reader"],
                          dbname=load.MAINTENANCE_DATABASE)
                yield
        finally:
            subprocess.run(["pg_ctl", "-D", str(data), "-m", "fast", "-w", "stop"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def fixture_collection(root: Path, record: dict, *, status: str = "pass", expected_hash: str | None = None,
                       contract_hash: str | None = None, missing: bool = False,
                       drop_contract_field: str | None = None) -> Path:
    full = root / "full"
    (full / "state").mkdir(parents=True)
    contract_path = full / "field-contract.json"
    contract_path.write_bytes((ROOT / "field-contract.json").read_bytes())
    if drop_contract_field:
        contract = load.load_json(contract_path)
        contract[0].pop(drop_contract_field)
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
    artifact = full / "normalized" / "fixture.jsonl"
    artifact.parent.mkdir()
    if not missing:
        artifact.write_text(json.dumps(record, separators=(",", ":")) + "\n", encoding="utf-8")
    actual_hash = load.sha256_file(artifact) if artifact.exists() else "0" * 64
    manifest = {
        "contract_sha256": contract_hash or load.sha256_file(full / "field-contract.json"),
        "sources": {"fbi_cde": {
            "status": status,
            "normalized_rows": 1,
            "normalized_artifact": {
                "path": "normalized/fixture.jsonl", "sha256": expected_hash or actual_hash, "rows": 1,
            },
        }},
    }
    (full / "state" / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return full


def duplicate_fixture(root: Path, records: list[dict]) -> Path:
    full = fixture_collection(root, records[0])
    artifact = full / "normalized" / "fixture.jsonl"
    artifact.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )
    manifest_path = full / "state" / "run-manifest.json"
    manifest = load.load_json(manifest_path)
    artifact_hash = load.sha256_file(artifact)
    manifest["sources"]["fbi_cde"]["normalized_rows"] = len(records)
    manifest["sources"]["fbi_cde"]["normalized_artifact"]["rows"] = len(records)
    manifest["sources"]["fbi_cde"]["normalized_artifact"]["sha256"] = artifact_hash
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return full


def census_geography_fixture(root: Path) -> Path:
    full = root / "full"
    (full / "state").mkdir(parents=True)
    (full / "normalized").mkdir()
    contract_path = full / "field-contract.json"
    contract_path.write_bytes((ROOT / "field-contract.json").read_bytes())
    contract = load.load_json(contract_path)
    census_fields = [row for row in contract if row["rate_limit_profile"] == "census_acs"
                     and row["planned_state"] == "run_now"]
    records = []
    for geo_type, geo_id, value in (
        ("state", "04000US06", 1.0),
        ("county", "05000US06001", 2.0),
        ("place", "16000US0600000", 3.0),
        ("tract", "14000US06001400100", 4.0),
    ):
        field = census_fields[len(records)]
        records.append({
            "geo_id": geo_id, "geo_type": geo_type, "year": "2024",
            "field_id": field["field_id"], "catalog_field_id": field["field_id"],
            "value": value, "unit": field["unit"], "source": "census_acs",
            "source_release": field["source_release"],
            "source_url": "https://api.census.gov/data/2024/acs/acs5",
            "methodology_note": "synthetic geography coverage fixture",
            "retrieved_at": "2026-09-19T00:00:00+00:00",
        })
    artifact = full / "normalized" / "census_acs.jsonl"
    artifact.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in records),
                        encoding="utf-8")
    manifest = {
        "contract_sha256": load.sha256_file(contract_path),
        "sources": {"census_acs": {
            "status": "pass", "normalized_rows": len(records),
            "normalized_artifact": {
                "path": "normalized/census_acs.jsonl",
                "sha256": load.sha256_file(artifact), "rows": len(records),
            },
        }},
    }
    (full / "state" / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return full


def zip_monitor_fixture(root: Path) -> Path:
    full = root / "full"
    (full / "state").mkdir(parents=True)
    (full / "normalized").mkdir()
    contract_path = full / "field-contract.json"
    contract_path.write_bytes((ROOT / "field-contract.json").read_bytes())
    contract = load.load_json(contract_path)
    records = {
        "irs_soi": {"geo_type": "zip", "geo_id": "zip:90210", "value": 1.0,
                    "source_url": "https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-zip-code-data"},
        "epa_airdata": {"geo_type": "monitor", "geo_id": "monitor:06-037-0001", "value": 2.0,
                        "source_url": "https://aqs.epa.gov/aqsweb/airdata/annual_conc_by_monitor_2024.zip"},
    }
    manifest_sources = {}
    for source, values in records.items():
        field = next(row for row in contract if row["rate_limit_profile"] == source
                     and row["planned_state"] == "run_now")
        record = {
            "geo_id": values["geo_id"], "geo_type": values["geo_type"], "year": "2024",
            "field_id": field["field_id"], "catalog_field_id": field["field_id"],
            "value": values["value"], "unit": field["unit"], "source": source,
            "source_release": field["source_release"], "source_url": values["source_url"],
            "methodology_note": "synthetic ZIP/monitor coverage fixture",
            "retrieved_at": "2026-09-19T00:00:00+00:00",
        }
        artifact = full / "normalized" / f"{source}.jsonl"
        artifact.write_text(json.dumps(record, separators=(",", ":")) + "\n", encoding="utf-8")
        manifest_sources[source] = {
            "status": "pass", "normalized_rows": 1,
            "normalized_artifact": {
                "path": f"normalized/{source}.jsonl", "sha256": load.sha256_file(artifact), "rows": 1,
            },
        }
    manifest = {"contract_sha256": load.sha256_file(contract_path), "sources": manifest_sources}
    (full / "state" / "run-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return full


class AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / "normalized" / "fbi_cde.jsonl").open(encoding="utf-8") as handle:
            cls.record = json.loads(next(handle))

    def test_valid_fixture_is_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            full = fixture_collection(Path(directory), self.record)
            admission = load.preflight_sources(["fbi_cde"], full)[0]
        self.assertEqual(admission.row_count, 1)

    def test_profile_mismatch_is_rejected(self):
        record = {**self.record, "catalog_field_id": "08.05", "field_id": "08.05:test"}
        with tempfile.TemporaryDirectory() as directory:
            full = fixture_collection(Path(directory), record)
            with self.assertRaisesRegex(load.AdmissionError, "catalog_field_source_mismatch"):
                load.preflight_sources(["fbi_cde"], full)

    def test_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            full = fixture_collection(Path(directory), self.record, expected_hash="0" * 64)
            with self.assertRaisesRegex(load.AdmissionError, "normalized_artifact_hash_mismatch"):
                load.preflight_sources(["fbi_cde"], full)


class PostgreSQLIntegrationTests(unittest.TestCase):
    def test_real_source_round_trip_idempotency_and_preflight_zero_writes(self):
        with postgres_cluster():
            with (ROOT / "normalized" / "fbi_cde.jsonl").open(encoding="utf-8") as handle:
                first_record = json.loads(next(handle))
            with mock.patch.dict(os.environ, {"PGDATABASE": "poisoned_ambient_database"}):
                first = load.load_database(["fbi_cde"], ROOT)
            self.assertEqual(first.sources, (("fbi_cde", "loaded"),))
            expected_rows = int(load.load_json(ROOT / "state" / "run-manifest.json")["sources"]["fbi_cde"]["normalized_rows"])
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.catalog_field")), 81)
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.observation")), expected_rows)
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.ingest_run WHERE status='pass'")), 1)

            key_sql = (
                "SELECT json_build_object(" 
                "'geo_id',geo_id,'geo_type',geo_type,'year',period,'field_id',field_id," 
                "'catalog_field_id',catalog_field_id,'value',value,'unit',unit,'source',source," 
                "'source_release',source_release,'source_url',source_url," 
                "'methodology_note',methodology_note,'retrieved_at',retrieved_at) "
                "FROM usa_atlas.observation ORDER BY geo_id,period,field_id,source_release LIMIT 1"
            )
            observed = json.loads(scalar(key_sql))
            with (ROOT / "normalized" / "fbi_cde.jsonl").open(encoding="utf-8") as handle:
                expected = min(
                    (json.loads(line) for line in handle),
                    key=lambda row: (row["geo_id"], row["year"], row["field_id"], row["source_release"]),
                )
            self.assertEqual({k: v for k, v in observed.items() if k != "retrieved_at"},
                             {k: v for k, v in expected.items() if k != "retrieved_at"})
            self.assertEqual(load.parse_timestamp(observed["retrieved_at"]),
                             load.parse_timestamp(expected["retrieved_at"]))

            second = load.load_database(["fbi_cde"], ROOT)
            self.assertEqual(second.sources, (("fbi_cde", "skipped"),))
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.observation")), expected_rows)
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.ingest_run")), 1)
            verified = load.verify_database(["fbi_cde"], ROOT)
            self.assertEqual(verified["status"], "pass")
            self.assertTrue(verified["checks"]["idempotent"])

            baseline = (
                int(scalar("SELECT count(*) FROM usa_atlas.observation")),
                int(scalar("SELECT count(*) FROM usa_atlas.ingest_run")),
            )
            invalid_cases = [
                {"status": "fail"},
                {"missing": True},
                {"expected_hash": "0" * 64},
                {"contract_hash": "0" * 64},
                {"record": {**first_record, "source": "eia"}},
                {"record": {**first_record, "catalog_field_id": "99.99", "field_id": "99.99:test"}},
                {"record": {**first_record, "catalog_field_id": "08.05", "field_id": "08.05:test"}},
                {"drop_contract_field": "catalog_label"},
            ]
            for case in invalid_cases:
                with self.subTest(case=sorted(case)):
                    record = case.pop("record", first_record)
                    with tempfile.TemporaryDirectory() as directory:
                        full = fixture_collection(Path(directory), record, **case)
                        with self.assertRaises(load.AdmissionError):
                            load.load_database(["fbi_cde"], full)
                    observed_counts = (
                        int(scalar("SELECT count(*) FROM usa_atlas.observation")),
                        int(scalar("SELECT count(*) FROM usa_atlas.ingest_run")),
                    )
                    self.assertEqual(observed_counts, baseline)

            with tempfile.TemporaryDirectory() as directory:
                duplicate_full = duplicate_fixture(Path(directory), [first_record, first_record])
                with self.assertRaisesRegex(load.AdmissionError, "target_complete_state_mismatch"):
                    load.load_database(["fbi_cde"], duplicate_full)
            self.assertEqual((
                int(scalar("SELECT count(*) FROM usa_atlas.observation")),
                int(scalar("SELECT count(*) FROM usa_atlas.ingest_run")),
            ), baseline)

            load.psql(["--command", "CREATE TABLE public.unexpected_user_object (id integer)"])
            with self.assertRaisesRegex(load.AdmissionError, "target_physical_schema_mismatch"):
                load.load_database(["fbi_cde"], ROOT)
            self.assertEqual((
                int(scalar("SELECT count(*) FROM usa_atlas.observation")),
                int(scalar("SELECT count(*) FROM usa_atlas.ingest_run")),
            ), baseline)

            load.psql(["--command", "DROP TABLE public.unexpected_user_object"])
            load.psql(["--command",
                       "ALTER TABLE usa_atlas.observation_data ENABLE ROW LEVEL SECURITY"])
            with self.assertRaisesRegex(load.AdmissionError, "target_physical_schema_mismatch"):
                load.load_database(["fbi_cde"], ROOT)

    def test_cross_admission_duplicate_is_rejected_before_database_creation(self):
        with postgres_cluster():
            with (ROOT / "normalized" / "fbi_cde.jsonl").open(encoding="utf-8") as handle:
                record = json.loads(next(handle))
            with tempfile.TemporaryDirectory() as directory:
                full = duplicate_fixture(Path(directory), [record])
                with self.assertRaisesRegex(load.AdmissionError, "duplicate_canonical_key"):
                    load.load_database(["fbi_cde", "fbi_cde"], full)
            self.assertEqual(maintenance_scalar(
                "SELECT count(*) FROM pg_database WHERE datname='usa_atlas'"), "0")

    def test_source_failure_rolls_back_ingest_and_staging_rows(self):
        with postgres_cluster():
            with (ROOT / "normalized" / "fbi_cde.jsonl").open(encoding="utf-8") as handle:
                record = json.loads(next(handle))
            with tempfile.TemporaryDirectory() as directory:
                full = fixture_collection(Path(directory), record)
                with mock.patch.object(load, "observation_rows",
                                       side_effect=RuntimeError("synthetic_copy_failure")):
                    with self.assertRaisesRegex(RuntimeError, "synthetic_copy_failure"):
                        load.load_database(["fbi_cde"], full)
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.ingest_run")), 0)
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.observation_stage")), 0)
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.catalog_field_stage")), 0)

    def test_partial_target_and_owner_mismatch_fail_before_writes(self):
        with postgres_cluster():
            load.load_database(["fbi_cde"], ROOT)
            baseline = int(scalar("SELECT count(*) FROM usa_atlas.observation"))
            with self.assertRaisesRegex(load.AdmissionError, "target_complete_state_mismatch"):
                load.load_database(["fbi_cde", "eia"], ROOT)
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.observation")), baseline)

            load.psql(["--command", "CREATE ROLE usa_atlas_other LOGIN"] ,
                      dbname=load.MAINTENANCE_DATABASE)
            load.psql(["--command", "ALTER DATABASE usa_atlas OWNER TO usa_atlas_other"],
                      dbname=load.MAINTENANCE_DATABASE)
            with self.assertRaisesRegex(load.AdmissionError, "target_owner_mismatch"):
                load.load_database(["fbi_cde"], ROOT)

    def test_deep_census_geographies_are_admitted_without_collapsing(self):
        with postgres_cluster():
            with tempfile.TemporaryDirectory() as directory:
                full = census_geography_fixture(Path(directory))
                outcome = load.load_database(["census_acs"], full)
                self.assertEqual(outcome.sources, (("census_acs", "loaded"),))
            observed = scalar(
                "SELECT string_agg(geo_type, ',' ORDER BY geo_type) "
                "FROM (SELECT DISTINCT geo_type FROM usa_atlas.observation) levels"
            )
            self.assertEqual(observed, "county,place,state,tract")
            self.assertEqual(int(scalar("SELECT count(*) FROM usa_atlas.observation")), 4)

    def test_zip_and_monitor_geographies_are_admitted(self):
        with postgres_cluster():
            with tempfile.TemporaryDirectory() as directory:
                full = zip_monitor_fixture(Path(directory))
                outcome = load.load_database(["irs_soi", "epa_airdata"], full)
                self.assertEqual(dict(outcome.sources), {"irs_soi": "loaded", "epa_airdata": "loaded"})
            observed = scalar(
                "SELECT string_agg(geo_type, ',' ORDER BY geo_type) "
                "FROM (SELECT DISTINCT geo_type FROM usa_atlas.observation) levels"
            )
            self.assertEqual(observed, "monitor,zip")


if __name__ == "__main__":
    unittest.main()
