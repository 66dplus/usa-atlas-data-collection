import csv
import hashlib
import json
import pathlib
import tempfile
import unittest

from prepare import (
    adjudicate_contest,
    adjudicate_mode,
    election_geo,
    house_geo,
    load_boundary,
    make_contest_key,
    parse_acs,
    read_csv_rows,
    selected_party_value,
    validate_county_contract,
    write_jsonl,
)


class PreparationUnitTests(unittest.TestCase):
    def test_csv_dictreader_preserves_quoted_comma_and_exact_fields(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td) / "rows.csv"
            path.write_text('year,candidate,party,mode,candidatevotes,totalvotes\n2024,"JOBS, EQUALITY",OTHER,TOTAL,40,100\n', encoding="utf-8")
            rows, fields = read_csv_rows(path)
            self.assertEqual(fields, ["year", "candidate", "party", "mode", "candidatevotes", "totalvotes"])
            self.assertEqual(rows[0], {"year":"2024", "candidate":"JOBS, EQUALITY", "party":"OTHER", "mode":"TOTAL", "candidatevotes":"40", "totalvotes":"100"})

    def test_valid_fusion_rows_are_party_adjudicated_and_denominator_is_not_summed(self):
        rows = [
            {"candidate_label":"A Candidate", "party_normalized":"DEMOCRAT", "candidate_kind":"candidate", "candidate_votes":60, "source_total_votes":100, "source_value_status":"observed", "fusion_ticket":True},
            {"candidate_label":"A Candidate", "party_normalized":"WORKING FAMILIES", "candidate_kind":"candidate", "candidate_votes":10, "source_total_votes":100, "source_value_status":"observed", "fusion_ticket":True},
            {"candidate_label":"B Candidate", "party_normalized":"REPUBLICAN", "candidate_kind":"candidate", "candidate_votes":30, "source_total_votes":100, "source_value_status":"observed", "fusion_ticket":False},
        ]
        result = adjudicate_contest(rows, expected_source_rows=len(rows), source_complete=True)
        self.assertEqual(result["status"], "validated")
        self.assertEqual(result["denominator"], 100)
        self.assertEqual(result["party_totals"]["DEMOCRAT"], 60)
        self.assertEqual(result["party_totals"]["WORKING FAMILIES"], 10)
        self.assertEqual(selected_party_value(result, "GREEN"), (0, 0.0))
        self.assertEqual(selected_party_value(result, "DEMOCRAT"), (60, 0.6))

    def test_quarantine_does_not_relabel_valid_source_values(self):
        rows = [
            {"candidate_label":"Same", "party_normalized":"DEMOCRAT", "candidate_kind":"candidate", "candidate_votes":20, "source_total_votes":100, "source_value_status":"observed", "fusion_ticket":False},
            {"candidate_label":"Same", "party_normalized":"DEMOCRAT", "candidate_kind":"candidate", "candidate_votes":20, "source_total_votes":100, "source_value_status":"observed", "fusion_ticket":False},
        ]
        result = adjudicate_contest(rows, expected_source_rows=len(rows), source_complete=True)
        self.assertEqual(result["status"], "quarantined")
        self.assertIn("repeated_candidate_party_row", result["reasons"])
        self.assertTrue(all(row["source_value_status"] == "observed" for row in rows))
        self.assertEqual(selected_party_value(result, "DEMOCRAT"), (None, None))

    def test_truncated_candidate_partition_cannot_claim_absent_party_zero(self):
        rows = [
            {"candidate_label":"A", "party_normalized":"DEMOCRAT", "candidate_kind":"candidate", "candidate_votes":60, "source_total_votes":100, "source_value_status":"observed", "fusion_ticket":False},
            {"candidate_label":"B", "party_normalized":"REPUBLICAN", "candidate_kind":"candidate", "candidate_votes":30, "source_total_votes":100, "source_value_status":"observed", "fusion_ticket":False},
        ]
        result = adjudicate_contest(rows, expected_source_rows=3, source_complete=True)
        self.assertEqual(result["status"], "quarantined")
        self.assertIn("candidate_partition_incomplete", result["reasons"])
        self.assertEqual(selected_party_value(result, "GREEN"), (None, None))

    def test_unknown_source_completeness_cannot_claim_absent_party_zero(self):
        rows = [{"candidate_label":"A", "party_normalized":"DEMOCRAT", "candidate_kind":"candidate", "candidate_votes":100, "source_total_votes":100, "source_value_status":"observed", "fusion_ticket":False}]
        result = adjudicate_contest(rows, expected_source_rows=1, source_complete=False)
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(selected_party_value(result, "REPUBLICAN"), (None, None))

    def test_blank_election_mode_stays_distinct_and_unadjudicated(self):
        row = {"year":"2024", "county_fips":"06037", "mode":"", "stage":"GEN", "special":"false", "version":"v1"}
        key = make_contest_key(row, "president", {}, "test-release")
        self.assertEqual(key[6], "general")
        self.assertEqual(key[9], "UNSPECIFIED")
        # Numeric candidate fields can still be valid while aggregation remains quarantined.
        candidate = {"candidate_label":"A", "party_normalized":"DEMOCRAT", "candidate_kind":"candidate",
                     "candidate_votes":60, "source_total_votes":100, "source_value_status":"observed"}
        result = adjudicate_mode([candidate], key[9], expected_source_rows=1, source_complete=True)
        self.assertEqual(result["reasons"], ["source_mode_unspecified"])
        self.assertEqual(candidate["source_value_status"], "observed")
        self.assertEqual(selected_party_value(result, "DEMOCRAT"), (None, None))

    def test_house_ids_are_exact_boundary_ids_for_at_large_and_dc_delegate(self):
        boundaries = {
            "0200":{"state_fips":"02", "district_code":"00", "is_at_large":True, "is_nonvoting":False},
            "1198":{"state_fips":"11", "district_code":"98", "is_at_large":False, "is_nonvoting":True},
        }
        ak = house_geo({"state_fips":"2", "district":"0"}, boundaries)
        dc = house_geo({"state_fips":"11", "district":"0"}, boundaries)
        self.assertEqual((ak["geo_id"], ak["is_at_large"], ak["seat_type"]), ("0200", True, "voting_district"))
        self.assertEqual((dc["geo_id"], dc["is_at_large"], dc["seat_type"]), ("1198", False, "nonvoting_delegate"))
        self.assertNotIn("1100", boundaries)

    def test_2024_house_contest_requires_exact_pinned_geometry_identity(self):
        with self.assertRaisesRegex(ValueError, "does not match a pinned CD119"):
            election_geo({"year":"2024", "stage":"GEN", "special":"false", "state_fips":"6", "district":"99"}, "house", {})

    def test_aian_us_estimate_and_moe_are_retained(self):
        row = {"B02010_001E":"7990799", "B02010_001M":"48461", "B01003_001E":"334922499", "B01003_001M":"-555555555"}
        contract = {"nonmapping_source_geoids":[]}
        result = parse_acs(row, "us", contract)
        self.assertEqual(result["geo_type"], "nation")
        self.assertEqual(result["geo_id"], "US")
        self.assertEqual(result["value"], round(7990799/334922499*100, 8))
        self.assertEqual(result["raw_estimate_moe"], "48461")
        self.assertEqual(result["raw_denominator_moe"], "-555555555")

    def test_multiyear_identity_uses_both_window_endpoints(self):
        root = pathlib.Path(__file__).parents[2]
        sql = (root / "database/reader/v2/fixtures/reader-query.sql").read_text()
        protocol = (root / "database/reader/v2/consumer-protocol.md").read_text()
        self.assertIn("period_start_year = $5", sql)
        self.assertIn("period_end_year = $6", sql)
        self.assertIn("period_start_year = :period_start_year", protocol)
        self.assertIn("period_end_year = :period_end_year", protocol)

    def test_county_contract_requires_exact_precheck_ids(self):
        with tempfile.TemporaryDirectory() as td:
            path = pathlib.Path(td)/"contract.json"
            contract = {"matching_rule":"exact five-digit GEOID only; no allocation or predecessor geography substitutions", "nonmapping_source_geoids":["02063","02066","09110","09120","09130","09140","09150","09160","09170","09180","09190"]}
            path.write_text(json.dumps(contract))
            self.assertEqual(len(validate_county_contract(path)["nonmapping_source_geoids"]),11)

    def test_wrong_boundary_hash_fails_before_use(self):
        with tempfile.TemporaryDirectory() as td:
            path=pathlib.Path(td)/"boundary.geojson"
            path.write_text('{"type":"FeatureCollection","features":[]}')
            args=type("Args",(),{"boundary_zip":None,"boundary_geojson":path,"boundary_geojson_sha256":"0"*64})()
            with self.assertRaisesRegex(ValueError,"trusted SHA-256"):
                load_boundary(args,pathlib.Path(td)/"out")

if __name__ == "__main__":
    unittest.main()
