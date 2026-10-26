from __future__ import annotations

import json
import os
import csv
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import URLError

from full.data_refresh_20261026 import refresh


class FakeResponse:
    def __init__(self, data: bytes, status: int = 200, headers: dict | None = None):
        self.data = data
        self.status = status
        self.headers = headers or {"Content-Length": str(len(data)), "Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1):
        if size < 0:
            data, self.data = self.data, b""
            return data
        data, self.data = self.data[:size], self.data[size:]
        return data


class RefreshTests(unittest.TestCase):
    def test_nsa_series_ids_and_period_types(self):
        self.assertEqual(refresh.bls_series_id("state", "06", "03"), "LAUST060000000000003")
        self.assertEqual(refresh.bls_series_id("county", "06037", "04"), "LAUCN060370000000004")
        self.assertEqual(refresh.period_info("2025", "M12"), ("2025-12", "monthly"))
        self.assertEqual(refresh.period_info("2025", "M13"), ("2025", "annual"))

    def test_bls_retains_missing_october_and_separate_annual_m13(self):
        sid = "LAUST060000000000003"
        meta = {sid: {"geo_id": "06", "geo_type": "state", "measure_code": "03"}}
        payload = json.dumps({"status": "REQUEST_SUCCEEDED", "Results": {"series": [{
            "seriesID": sid,
            "data": [
                {"year": "2025", "period": "M09", "value": "4.2", "footnotes": []},
                {"year": "2025", "period": "M10", "value": "-", "footnotes": [{"text": "Data unavailable"}]},
                {"year": "2025", "period": "M13", "value": "4.1", "footnotes": []},
            ],
        }]}}).encode()
        values, missing = refresh.parse_bls_payload(payload, meta)
        self.assertEqual([(row["period"], row["period_type"]) for row in values],
                         [("2025-09", "monthly"), ("2025", "annual")])
        october = next(row for row in missing if row["bls_period_code"] == "M10")
        self.assertIsNone(october["value"])
        self.assertEqual(october["status"], "source_missing")
        self.assertTrue(any(row["bls_period_code"] == "M01" and row["status"] == "period_not_returned"
                            for row in missing))
        self.assertFalse(any(row.get("period") == "2025-12" and row.get("value") == "4.1" for row in values))

    def test_fbi_actuals_and_rates_are_separate_monthly_source_values(self):
        payload = json.dumps({"offenses": {
            "actuals": {"Alabama Offenses": {"01-2025": 0}},
            "rates": {"Alabama Offenses": {"01-2025": 0.0}},
        }}).encode()
        values, missing = refresh.fbi_response_rows(payload, "AL", "04.01", "homicide")
        self.assertEqual(len(values), 2)
        self.assertEqual({row["source_field"] for row in values}, {"actuals", "rates"})
        self.assertEqual({row["period_type"] for row in values}, {"monthly"})
        self.assertTrue(all(row["source_value"] in {"0", "0.0"} for row in values))
        self.assertEqual(len(missing), 22)  # Remaining months are explicit missingness, not zero.
        self.assertFalse(any(row.get("period_type") == "annual" for row in values))

    def test_income_requires_matching_year_and_converts_thousands_to_usd(self):
        self.assertEqual(refresh.income_per_resident(Decimal("1250"), 500, "2023", "2023"), Decimal("2500"))
        self.assertIsNone(refresh.income_per_resident(Decimal("1250"), None, "2023", "2023"))
        with self.assertRaisesRegex(ValueError, "year_mismatch"):
            refresh.income_per_resident(Decimal("1250"), 500, "2023", "2024")

    def test_pep_year_mapping_and_missing_integer_values(self):
        self.assertEqual(refresh.pep_year_for_source("2023"), "4")
        self.assertEqual(refresh.pep_year_for_source("2024"), "5")
        self.assertIsNone(refresh.safe_int("-"))
        self.assertIsNone(refresh.safe_int(""))
        self.assertEqual(refresh.safe_int("1,234"), 1234)

    def test_population_uses_county_both_sex_totals_and_ages_0_through_17(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            totals = runtime / "raw/census/pep-v2025/co-est2025-alldata.csv"
            ages = runtime / "raw/census/pep-v2025/cc-est2025-syasex.csv"
            national = runtime / "raw/census/pep-v2025/nc-est2025-agesex-res.csv"
            for path in (totals, ages, national):
                path.parent.mkdir(parents=True, exist_ok=True)
            with totals.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["SUMLEV", "STATE", "COUNTY", "POPESTIMATE2023", "POPESTIMATE2024"])
                writer.writeheader()
                writer.writerows([
                    {"SUMLEV": "050", "STATE": "01", "COUNTY": "001", "POPESTIMATE2023": "1000", "POPESTIMATE2024": "1100"},
                    {"SUMLEV": "040", "STATE": "01", "COUNTY": "000", "POPESTIMATE2023": "1000", "POPESTIMATE2024": "1100"},
                    {"SUMLEV": "010", "STATE": "00", "COUNTY": "000", "POPESTIMATE2023": "1000", "POPESTIMATE2024": "1100"},
                ])
            with ages.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["STATE", "COUNTY", "YEAR", "AGE", "TOT_POP"])
                writer.writeheader()
                writer.writerows({"STATE": "01", "COUNTY": "001", "YEAR": year, "AGE": age, "TOT_POP": "1"}
                                 for year in ("4", "5") for age in range(18))
            with national.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["SEX", "AGE", "POPESTIMATE2023", "POPESTIMATE2024"])
                writer.writeheader()
                writer.writerows({"SEX": sex, "AGE": age, "POPESTIMATE2023": value, "POPESTIMATE2024": value}
                                 for sex, value in (("0", "1"), ("1", "99")) for age in range(18))
            with mock.patch.object(refresh, "RUNTIME", runtime):
                result = refresh.prepare_population()
                rows = list(refresh.read_csv(runtime / "prepared/population-2023-2024.csv"))
        county_2023 = {row["population_kind"]: int(row["value"]) for row in rows
                       if row["geo_id"] == "01001" and row["year"] == "2023"}
        self.assertEqual(county_2023, {"total": 1000, "under_18": 18, "age_13_plus": 987})
        national_2023 = {row["population_kind"]: int(row["value"]) for row in rows
                         if row["geo_id"] == "US" and row["year"] == "2023"}
        self.assertEqual(national_2023["under_18"], 18)
        self.assertEqual(national_2023["age_13_plus"], 987)
        self.assertEqual(result["status"], "partial")  # Missing geographies stay unresolved.

    def test_medical_rates_use_matching_age_denominators_and_preserve_suppression(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            pop = runtime / "prepared/population-2023-2024.csv"
            pop.parent.mkdir(parents=True)
            with pop.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["geo_type", "geo_id", "year", "population_kind", "value"])
                writer.writeheader()
                writer.writerows([
                    {"geo_type": "state", "geo_id": "01", "year": "2023", "population_kind": "total", "value": 100},
                    {"geo_type": "state", "geo_id": "01", "year": "2024", "population_kind": "total", "value": 100},
                    {"geo_type": "state", "geo_id": "01", "year": "2024", "population_kind": "age_13_plus", "value": 90},
                    {"geo_type": "state", "geo_id": "01", "year": "2024", "population_kind": "under_18", "value": 10},
                ])
            receipts = {}
            for key, metric, year, value in [("cancer2023", "11.01", "2023", 2),
                                              ("hiv2024", "11.02", "2024", 3),
                                              ("childDeaths2024", "11.03", "2024", 1)]:
                path = runtime / f"{key}.jsonl"
                path.write_text(json.dumps({"geo_type": "state", "geo_id": "01", "year": year,
                                            "field_id": metric, "value": value, "source_release": "fixture",
                                            "source_url": "https://example.gov", "retrieved_at": "2026-10-01"}) + "\n")
                receipts[key] = path
            with mock.patch.object(refresh, "RUNTIME", runtime), mock.patch.object(refresh, "MEDICAL_RECEIPTS", receipts):
                result = refresh.prepare_existing_medical_rates()
                cancer = list(refresh.read_csv(runtime / "prepared/cancer-2023-rates.csv"))[0]
                hiv = list(refresh.read_csv(runtime / "prepared/hiv-2024-rates.csv"))[0]
                child = list(refresh.read_csv(runtime / "prepared/child-deaths-under18-2024-rates.csv"))
        self.assertEqual(cancer["denominator_kind"], "total")
        self.assertEqual(cancer["denominator_year"], "2023")
        self.assertEqual(Decimal(cancer["value"]), Decimal(2000))
        self.assertEqual(hiv["denominator_kind"], "age_13_plus")
        self.assertEqual(Decimal(hiv["value"]), Decimal(100000) / Decimal(30))
        self.assertEqual(child, [])
        self.assertEqual(result["childDeaths2024"]["missingness"][0]["status"], "source_suppressed")

    def test_download_preserves_exact_source_bytes_and_hash(self):
        raw = b"source\x00bytes\n"
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(refresh, "RUNTIME", Path(temp)):
                with mock.patch.object(refresh, "urlopen", return_value=FakeResponse(raw)):
                    record = refresh.download_file("unit-source", "https://example.gov/data", "input.bin")
                stored = (Path(temp) / "raw/input.bin").read_bytes()
                self.assertEqual(stored, raw)
                self.assertEqual(record["sha256"], refresh.sha256_bytes(raw))
                self.assertTrue(record["retrievedAt"])

    def test_bls_injected_key_never_enters_artifact_or_error_metadata(self):
        key = "SYNTHETIC-BLS-KEY-DO-NOT-LEAK"
        sid = refresh.bls_series_id("state", "06", "03")
        series = [{"series_id": sid, "geo_id": "06", "geo_type": "state", "measure_code": "03"}]
        response = json.dumps({"status": "REQUEST_SUCCEEDED", "Results": {"series": [{
            "seriesID": sid, "data": [{"year": "2025", "period": "M01", "value": "4.0", "footnotes": []}],
        }]}}).encode()
        captured = {}

        def fake_request(url, body, headers, timeout):
            captured["url"] = url
            captured["body"] = body
            return response, 200, {"Content-Type": "application/json"}

        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"BLS_API_KEY": key}):
            with mock.patch.object(refresh, "RUNTIME", Path(temp)), mock.patch.object(refresh, "request_bytes", side_effect=fake_request):
                _values, _missing, artifact = refresh.fetch_bls_batch(0, series, 1)
                qhash, fingerprint = refresh.bls_batch_fingerprint(series, 0, 24)
                base = Path(temp) / f"raw/bls/plans/{qhash}/{fingerprint}"
                metadata = base.with_suffix(".meta.json").read_text()
                raw = base.with_suffix(".json").read_bytes()
        self.assertIn(key.encode(), captured["body"])
        self.assertNotIn(key, json.dumps(artifact) + metadata)
        self.assertNotIn(key.encode(), raw)
        self.assertEqual(artifact["credentialMode"], "registered")

    def test_bls_changed_ordered_queue_gets_distinct_cache_plan(self):
        sid_a = refresh.bls_series_id("state", "06", "03")
        sid_b = refresh.bls_series_id("state", "06", "04")
        first = [{"series_id": sid_a, "geo_id": "06", "geo_type": "state", "measure_code": "03"}]
        changed = [first[0], {"series_id": sid_b, "geo_id": "06", "geo_type": "state", "measure_code": "04"}]
        payload = json.dumps({"status": "REQUEST_SUCCEEDED", "Results": {"series": []}}).encode()
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"BLS_API_KEY": "SYNTHETIC-KEY"}):
            with mock.patch.object(refresh, "RUNTIME", Path(temp)), mock.patch.object(
                    refresh, "request_bytes", return_value=(payload, 200, {})) as request:
                refresh.fetch_bls_batch(0, first, 1, 50)
                refresh.fetch_bls_batch(0, changed, 1, 50)
                self.assertEqual(request.call_count, 2)
                q1, f1 = refresh.bls_batch_fingerprint(first, 0, 50)
                q2, f2 = refresh.bls_batch_fingerprint(changed, 0, 50)
                self.assertNotEqual(q1, q2)
                self.assertNotEqual(f1, f2)

    def test_bls_corrupt_cached_raw_hash_is_refetched(self):
        sid = refresh.bls_series_id("state", "06", "03")
        series = [{"series_id": sid, "geo_id": "06", "geo_type": "state", "measure_code": "03"}]
        payload = json.dumps({"status": "REQUEST_SUCCEEDED", "Results": {"series": []}}).encode()
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"BLS_API_KEY": "SYNTHETIC-KEY"}):
            with mock.patch.object(refresh, "RUNTIME", Path(temp)), mock.patch.object(
                    refresh, "request_bytes", return_value=(payload, 200, {})) as request:
                refresh.fetch_bls_batch(0, series, 1, 50)
                _queue, fingerprint = refresh.bls_batch_fingerprint(series, 0, 50)
                raw_path = Path(temp) / f"raw/bls/plans/{_queue}/{fingerprint}.json"
                raw_path.write_bytes(b"corrupted raw")
                values, missing, artifact = refresh.fetch_bls_batch(0, series, 1, 50)
                self.assertEqual(request.call_count, 2)
                self.assertEqual(artifact["status"], "downloaded")
                self.assertEqual(artifact["sha256"], refresh.sha256_file(raw_path))

    def test_bls_completed_checkpoint_rejects_corrupted_raw_and_counts_refetch(self):
        geo = {"geo_type": "state", "geo_id": "01", "name": "Alabama"}
        queue = refresh.make_bls_queue([geo], {})
        qhash = refresh.sha256_bytes(json.dumps([item["series_id"] for item in queue], separators=(",", ":")).encode())
        plan_id = refresh.sha256_bytes(f"{refresh.BLS_PLAN_VERSION}:{qhash}:50".encode())[:20]
        _queue_hash, fingerprint = refresh.bls_batch_fingerprint(queue, 0, 50)
        response = json.dumps({"status": "REQUEST_SUCCEEDED", "Results": {"series": []}}).encode()
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"BLS_API_KEY": "SYNTHETIC-KEY"}):
            root = Path(temp)
            raw = root / f"raw/bls/plans/{qhash}/{fingerprint}.json"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b"corrupted raw")
            raw.with_suffix(".meta.json").write_text(json.dumps({"sha256": "wrong", "queueHash": qhash,
                                                                   "requestFingerprint": fingerprint,
                                                                   "planVersion": refresh.BLS_PLAN_VERSION}))
            checkpoint = root / f"state/bls-checkpoint-{plan_id}.json"
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text(json.dumps({"format": "bls_checkpoint_v2", "completedBatchNumbers": [0],
                                              "queueHash": qhash, "planVersion": refresh.BLS_PLAN_VERSION,
                                              "batchSize": 50}))
            with mock.patch.object(refresh, "RUNTIME", root), mock.patch.object(
                    refresh, "load_population_for_bls", return_value=([geo], {})), mock.patch.object(
                    refresh, "request_bytes", return_value=(response, 200, {})) as request:
                result = refresh.collect_bls(1)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(result["queriesThisRun"], 1)
            self.assertNotEqual(refresh.sha256_file(raw), refresh.sha256_bytes(b"corrupted raw"))

    def test_url_encoded_injected_secret_is_rejected_from_source_bytes(self):
        key = "SYNTHETIC/ENCODED KEY"
        with mock.patch.dict(os.environ, {"EIA_API_KEY": key}):
            self.assertFalse(refresh.source_bytes_safe(refresh.urllib.parse.quote(key, safe="").encode()))

    def test_eia_keyed_url_and_errors_are_sanitized(self):
        key = "SYNTHETIC-EIA-KEY-DO-NOT-LEAK"
        fake_rows = [{"period": "2025", "stateid": abbr, "sectorid": "ALL",
                      "price": None if abbr == "AL" else "12.3", "price-units": "cents per kilowatthour"}
                     for abbr, _name, _fips in refresh.FBI_STATES]
        response = json.dumps({"response": {"data": fake_rows}}).encode()
        captured_url = []
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"EIA_API_KEY": key}):
            with mock.patch.object(refresh, "RUNTIME", Path(temp)), mock.patch.object(
                    refresh, "request_bytes", side_effect=lambda url, **_kwargs: (captured_url.append(url) or (response, 200, {}))):
                artifact = refresh.fetch_eia_api()
                rows, summary = refresh.parse_eia_api(response)
            serialized = json.dumps(artifact) + json.dumps(summary) + json.dumps(rows)
            self.assertEqual(len(rows), 51)
            self.assertIsNone(next(row for row in rows if row["state"] == "AL")["value"])
            self.assertIn(key, captured_url[0])
            self.assertNotIn(key, serialized)
            with mock.patch.object(refresh, "request_bytes", side_effect=URLError(f"failed api_key={key}")):
                failed = refresh.fetch_eia_api()
            self.assertNotIn(key, json.dumps(failed))
            self.assertNotIn("detail", failed)
            stored = (Path(temp) / "raw/eia/electricity-retail-sales-2025-all.json").read_bytes()
            self.assertNotIn(key.encode(), stored)

    def test_provider_response_echoing_key_is_not_saved(self):
        key = "SYNTHETIC-ECHO-KEY-DO-NOT-LEAK"
        response = json.dumps({"error": key}).encode()
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"EIA_API_KEY": key}):
            with mock.patch.object(refresh, "RUNTIME", Path(temp)), mock.patch.object(
                    refresh, "request_bytes", return_value=(response, 200, {})):
                artifact = refresh.fetch_eia_api()
            self.assertEqual(artifact["status"], "blocked_secret_echo")
            self.assertNotIn(key, json.dumps(artifact))
            self.assertFalse((Path(temp) / "raw/eia/electricity-retail-sales-2025-all.json").exists())

    def test_definition_matrix_covers_published_42_with_readiness_fields(self):
        matrix = json.loads((refresh.PACKAGE / "definition_matrix.json").read_text())
        self.assertEqual(matrix["scopeCount"], 42)
        self.assertEqual(len(matrix["rows"]), 42)
        required = {"definition", "numerator", "denominator", "unit", "geography",
                    "observationPeriod", "observationType", "releaseDate", "retrievalDate",
                    "latestSuitableRelease", "limitations", "status"}
        for row in matrix["rows"]:
            self.assertTrue(required.issubset(row))
            self.assertNotEqual(row["status"], "not_reviewed_in_focused_refresh")

    def test_runtime_matrix_does_not_claim_annual_fbi_values_from_monthly_data(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(refresh, "RUNTIME", Path(temp)):
            path = Path(refresh.write_runtime_matrix({"fbiCrime": {"status": "complete"}}))
            rows = json.loads(path.read_text())["rows"]
        crime = [row for row in rows if row["sourceId"] == "fbi-cde-state"]
        self.assertEqual(len(crime), 7)
        self.assertTrue(all(row["status"] == "monthly_source_series_complete_annual_values_not_synthesized"
                            for row in crime))

    def test_fbi_annual_comparison_leaves_new_year_missing_without_official_table(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            baseline = root / "full/normalized/fbi_cde.jsonl"
            baseline.parent.mkdir(parents=True)
            baseline.write_text(json.dumps({"geo_id": "AL", "geo_type": "state", "year": "2023",
                                            "field_id": "04.01", "value": 5,
                                            "methodology_note": "Annual sum of monthly actuals"}) + "\n")
            with mock.patch.object(refresh, "ROOT", root), mock.patch.object(refresh, "RUNTIME", root / "runtime"):
                result = refresh.prepare_fbi_baseline_and_pending_annual()
                rows = list(refresh.read_csv(root / "runtime/prepared/fbi-2023-baseline-2025-annual-pending.csv"))
        al = next(row for row in rows if row["field_id"] == "04.01" and row["state"] == "AL")
        self.assertEqual(al["before_value"], "5")
        self.assertEqual(al["after_annual_value"], "")
        self.assertEqual(al["after_status"], "official_state_annual_estimate_table_not_captured")
        self.assertEqual(result["annual2025Rows"], 0)


if __name__ == "__main__":
    unittest.main()
