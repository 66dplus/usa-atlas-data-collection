import json
import math
import tempfile
import unittest
from pathlib import Path

import collect
import collect_housing_stock_2021 as housing


HERE = Path(__file__).resolve().parent
CONTRACT = collect.load_json(HERE / "housing-stock-2021-contract.json")
METRICS = collect.load_json(HERE / "housing-stock-2021-metrics.json")
METHOD_NOTE = (
    "Chugach Census Area (02063) and Copper River Census Area (02066) are combined "
    "into the 2017 Valdez-Cordova Census Area (02261) boundary; the union differs "
    "from the 2017 boundary by 0.004% of area (a coastal/glacier sliver). Counts are "
    "summed; the share is computed from the summed numerator and denominator."
)


def source_values(total, occupied, vacant, owner, renter):
    return {
        "B25001_001E": total, "B25001_001M": 10,
        "B25002_001E": total, "B25002_001M": 10,
        "B25002_002E": occupied, "B25002_002M": 8,
        "B25002_003E": vacant, "B25002_003M": 6,
        "B25003_001E": occupied, "B25003_001M": 8,
        "B25003_002E": owner, "B25003_002M": 5,
        "B25003_003E": renter, "B25003_003M": 4,
    }


def record(geo_id, values):
    return {
        "geo_id": geo_id,
        "geo_type": "county",
        "geo_name": geo_id,
        "source_url": "https://api.census.gov/data/2021/acs/acs5",
        "source_values": values,
        "missing_source_fields": [],
    }


class ContractTests(unittest.TestCase):
    def test_contract_is_period_specific_and_keeps_2024_legacy(self):
        self.assertEqual(CONTRACT["source_release"], "2021-acs-acs5")
        self.assertEqual(CONTRACT["period"], "2017-2021")
        self.assertEqual(CONTRACT["expected_counts"], {"nation": 1, "state": 51, "county": 3142})
        self.assertEqual(len(CONTRACT["source_variables"]), 14)
        contract = collect.load_json(collect.CONTRACT_PATH)
        legacy = next(item for item in contract if item["field_id"] == "02.07")
        self.assertEqual(legacy["source_release"], "2024-acs-acs5")
        self.assertIn("B25001_001E", legacy["source_variables"])

    def test_three_indicators_use_all_housing_units(self):
        self.assertEqual([item["id"] for item in METRICS["indicators"]], [
            "02.07:owner_occupied_share_all_units",
            "02.07:renter_occupied_share_all_units",
            "02.07:vacant_share_all_units",
        ])
        self.assertEqual([item["label"] for item in METRICS["indicators"]], [
            "Owner-occupied homes", "Renter-occupied homes", "Vacant homes",
        ])
        for indicator in METRICS["indicators"]:
            self.assertEqual(indicator["denominator"], "B25001_001E")
            self.assertEqual(indicator["unit"], "% of all housing units")
            self.assertEqual(indicator["period"], "2017-2021")
            self.assertEqual(indicator["sourceRelease"], "2021-acs-acs5")
            self.assertIn(METHOD_NOTE, indicator["method"])

    def test_geometry_check_matches_approved_tolerance(self):
        check = CONTRACT["alaska_aggregation"]["geometry_check"]
        self.assertEqual(check["symmetric_difference_pct"], 0.0039)
        self.assertEqual(check["approved_tolerance_pct"], 0.004)
        self.assertTrue(check["approved"])


class ParsingTests(unittest.TestCase):
    def test_parse_rows_excludes_puerto_rico(self):
        variables = CONTRACT["source_variables"]
        header = ["NAME", *variables, "state", "county"]
        values = source_values(200, 150, 50, 90, 60)
        ca = ["California County", *[values[v] for v in variables], "06", "001"]
        pr = ["Puerto Rico County", *[values[v] for v in variables], "72", "001"]
        records, missing = housing.parse_rows(
            [header, ca, pr], CONTRACT, "county", "https://api.census.gov/data/2021/acs/acs5",
        )
        self.assertEqual(missing, [])
        self.assertEqual([item["geo_id"] for item in records], ["06001"])
        self.assertEqual(records[0]["geo_name"], "California County")
        self.assertEqual(records[0]["source_release"], "2021-acs-acs5")
        self.assertEqual(records[0]["display_period"], "2017–2021")


class AlaskaTests(unittest.TestCase):
    def test_alaska_aggregation_sums_counts_and_rss_moes(self):
        chugach = record("02063", source_values(100, 80, 20, 50, 30))
        copper = record("02066", source_values(40, 30, 10, 20, 10))
        other = record("02020", source_values(10, 8, 2, 5, 3))
        records = [chugach, copper, other]
        aggregated = housing.aggregate_alaska(records, CONTRACT)
        self.assertIsNotNone(aggregated)
        self.assertEqual(aggregated["geo_id"], "02261")
        self.assertEqual(aggregated["geo_name"], "Valdez-Cordova Census Area, Alaska")
        self.assertEqual(aggregated["source_values"]["B25001_001E"], 140)
        self.assertEqual(aggregated["source_values"]["B25001_001M"], math.sqrt(200))
        self.assertNotIn("02063", [item["geo_id"] for item in records])
        self.assertNotIn("02066", [item["geo_id"] for item in records])
        self.assertIn("02261", [item["geo_id"] for item in records])

    def test_alaska_shares_use_summed_counts(self):
        values = source_values(140, 110, 30, 70, 40)
        item = record("02261", values)
        housing.add_counts_and_metrics(item, METRICS["indicators"])
        self.assertAlmostEqual(item["metrics"]["02.07:owner_occupied_share_all_units"]["value"], 50.0)
        self.assertAlmostEqual(item["metrics"]["02.07:renter_occupied_share_all_units"]["value"], 28.5714)
        self.assertAlmostEqual(item["metrics"]["02.07:vacant_share_all_units"]["value"], 21.4286)


class BoundaryTests(unittest.TestCase):
    def test_boundary_ids_must_match_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "06.json").write_text(json.dumps({
                "features": [{"id": "06001"}, {"id": "06075"}],
            }))
            (root / "02.json").write_text(json.dumps({
                "features": [{"id": "02261"}],
            }))
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "states": [{"id": "02"}, {"id": "06"}],
            }))
            records = [
                {"geo_type": "county", "geo_id": "06001"},
                {"geo_type": "county", "geo_id": "06075"},
                {"geo_type": "county", "geo_id": "02261"},
            ]
            result = housing.validate_boundaries(records, manifest)
            self.assertTrue(result["pass"])
            self.assertEqual(result["boundary_counties"], 3)


class MetricTests(unittest.TestCase):
    def test_shares_use_all_units_denominator(self):
        item = record("06075", source_values(200, 150, 50, 90, 60))
        housing.add_counts_and_metrics(item, METRICS["indicators"])
        self.assertEqual(item["counts"]["total_housing_units"]["estimate"], 200)
        self.assertEqual(item["metrics"]["02.07:owner_occupied_share_all_units"]["numerator"], 90)
        self.assertEqual(item["metrics"]["02.07:owner_occupied_share_all_units"]["denominator"], 200)
        self.assertAlmostEqual(item["metrics"]["02.07:owner_occupied_share_all_units"]["value"], 45.0)
        self.assertAlmostEqual(item["metrics"]["02.07:renter_occupied_share_all_units"]["value"], 30.0)
        self.assertAlmostEqual(item["metrics"]["02.07:vacant_share_all_units"]["value"], 25.0)

    def test_missing_values_are_reported(self):
        values = source_values(200, 150, 50, 90, 60)
        values["B25003_002M"] = None
        header = ["NAME", *CONTRACT["source_variables"], "state", "county"]
        row = ["Missing County", *[values[v] for v in CONTRACT["source_variables"]], "06", "001"]
        records, missing = housing.parse_rows(
            [header, row], CONTRACT, "county", "https://api.census.gov/data/2021/acs/acs5",
        )
        self.assertEqual(missing, ["06001"])
        self.assertEqual(records[0]["missing_source_fields"], ["B25003_002M"])


if __name__ == "__main__":
    unittest.main()
